"""
OpenTelemetry integration for Saga Orchestrator.

Provides distributed tracing with automatic span creation and context propagation.
"""

import logging
from typing import Optional, Any, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# =========================================================================
# OpenTelemetry Telemetry Collector
# =========================================================================

class SagaTelemetryCollector:
    """
    Telemetry collector for OpenTelemetry integration.
    
    Can be connected to:
    - Jaeger (via OTLP)
    - DataDog
    - New Relic
    - AWS X-Ray (via ADOT)
    """
    
    def __init__(self, service_name: str = "saga-orchestrator", 
                 otlp_endpoint: Optional[str] = None,
                 enable_console_exporter: bool = False):
        """
        Initialize telemetry collector.
        
        Args:
            service_name: Name of the service for telemetry
            otlp_endpoint: OTEL Collector endpoint (e.g., http://localhost:4317)
            enable_console_exporter: Debug flag to print spans to console
        """
        self.service_name = service_name
        self.otlp_endpoint = otlp_endpoint or "http://localhost:4317"
        self.enable_console_exporter = enable_console_exporter
        self.active_spans: Dict[str, Any] = {}
        self.completed_spans: list = []
        
        logger.info(f"🔍 OpenTelemetry initialized for {service_name}")
        logger.info(f"   OTLP Endpoint: {self.otlp_endpoint}")
    
    # =====================================================================
    # Span Management
    # =====================================================================
    
    def create_trace_id(self) -> str:
        """Create a new trace ID (hex string)."""
        import uuid
        return uuid.uuid4().hex

    def start_span(self, span_name: str, 
                   attributes: Optional[Dict[str, Any]] = None,
                   *,
                   trace_id: Optional[str] = None,
                   parent_span_id: Optional[str] = None) -> str:
        """
        Start a new tracing span.
        
        Args:
            span_name: Name of the span (e.g., "saga.start", "saga.reserve")
            attributes: Additional attributes to attach to span
        
        Returns:
            Span ID for correlation
        """
        import uuid
        span_id = str(uuid.uuid4())
        trace_id = trace_id or self.create_trace_id()
        
        span = {
            "trace_id": trace_id,
            "span_id": span_id,
            "span_name": span_name,
            "parent_span_id": parent_span_id,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "attributes": attributes or {},
            "events": [],
            "end_time": None,
            "duration_ms": None,
        }
        
        self.active_spans[span_id] = span
        
        if self.enable_console_exporter:
            logger.debug(f"🔹 Span START: {span_name} [{span_id}]")
            if attributes:
                logger.debug(f"   Attributes: {attributes}")
        
        return span_id
    
    def add_span_event(self, span_id: str, event_name: str, 
                      event_attributes: Optional[Dict[str, Any]] = None):
        """
        Add an event to an active span.
        
        Args:
            span_id: The span to add event to
            event_name: Name of the event
            event_attributes: Event attributes
        """
        if span_id not in self.active_spans:
            logger.warning(f"⚠️  Span {span_id} not found")
            return
        
        event = {
            "name": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attributes": event_attributes or {},
        }
        
        self.active_spans[span_id]["events"].append(event)
        
        if self.enable_console_exporter:
            logger.debug(f"📍 Span EVENT: {event_name} in {span_id}")
    
    def end_span(self, span_id: str, 
                 status: str = "OK",
                 error: Optional[str] = None) -> Dict[str, Any]:
        """
        End a span and record it.
        
        Args:
            span_id: The span to end
            status: Span status (OK, ERROR, UNSET)
            error: Error message if status is ERROR
        
        Returns:
            Completed span data
        """
        if span_id not in self.active_spans:
            logger.warning(f"⚠️  Span {span_id} not found for ending")
            return {}
        
        span = self.active_spans.pop(span_id)
        
        # Calculate duration
        try:
            # Parse start time (ISO format)
            start_str = span["start_time"]
            start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            end = datetime.now(timezone.utc)
            duration_ms = (end - start).total_seconds() * 1000
            span["duration_ms"] = duration_ms
            span["end_time"] = end.isoformat()
            span["status"] = status
            if error:
                span["error"] = error
                span["attributes"]["error.type"] = type(error).__name__
                span["attributes"]["error.message"] = str(error)
        except Exception as e:
            logger.warning(f"⚠️  Error calculating span duration: {e}")
            span["duration_ms"] = 0
        
        self.completed_spans.append(span)
        
        if self.enable_console_exporter:
            logger.debug(
                f"🔺 Span END: {span['span_name']} [{span_id}] "
                f"({span['duration_ms']:.2f}ms) [{status}]"
            )
        
        return span
    
    # =====================================================================
    # Saga-Specific Tracing
    # =====================================================================
    
    def start_saga_trace(self, saga_id: str, correlation_id: str,
                        flow_name: str, *, trace_id: Optional[str] = None,
                        action_id: Optional[str] = None,
                        user_id: Optional[str] = None) -> str:
        """Start a saga trace (root span)."""
        return self.start_span(
            "saga.execute",
            attributes={
                "saga_id": saga_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
                "flow_name": flow_name,
                "action_id": action_id,
                "user_id": user_id,
                "service": self.service_name,
            }
            ,
            trace_id=trace_id
        )
    
    def start_adapter_call(self, span_parent_id: str,
                          adapter_name: str, method: str,
                          payload_size: int,
                          *,
                          trace_id: Optional[str] = None,
                          saga_id: Optional[str] = None,
                          correlation_id: Optional[str] = None) -> str:
        """Start an adapter call span."""
        return self.start_span(
            f"adapter.{adapter_name}.{method}",
            attributes={
                "adapter": adapter_name,
                "method": method,
                "payload_size": payload_size,
                "saga_id": saga_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
            ,
            trace_id=trace_id,
            parent_span_id=span_parent_id
        )
    
    def start_lock_acquisition(self, span_parent_id: str,
                              lock_key: str,
                              *,
                              trace_id: Optional[str] = None,
                              saga_id: Optional[str] = None,
                              correlation_id: Optional[str] = None) -> str:
        """Start a lock acquisition span."""
        return self.start_span(
            "lock.acquire",
            attributes={
                "lock_key": lock_key,
                "saga_id": saga_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
            ,
            trace_id=trace_id,
            parent_span_id=span_parent_id
        )
    
    def start_compensation_trace(self, span_parent_id: str,
                                saga_id: str,
                                *,
                                trace_id: Optional[str] = None,
                                correlation_id: Optional[str] = None) -> str:
        """Start a compensation trace."""
        return self.start_span(
            "saga.compensation",
            attributes={
                "saga_id": saga_id,
                "correlation_id": correlation_id,
                "trace_id": trace_id,
            }
            ,
            trace_id=trace_id,
            parent_span_id=span_parent_id
        )
    
    # =====================================================================
    # Span Export and Query
    # =====================================================================
    
    def export_spans(self, limit: int = 100) -> list:
        """
        Export completed spans for external telemetry systems.
        
        Returns:
            List of completed spans (most recent first)
        """
        return self.completed_spans[-limit:]
    
    def get_spans_by_correlation_id(self, correlation_id: str) -> list:
        """
        Get all spans for a correlation_id (useful for tracing full request).
        
        Args:
            correlation_id: The correlation ID to search for
        
        Returns:
            List of matching spans
        """
        matching = [
            span for span in self.completed_spans
            if span.get("attributes", {}).get("correlation_id") == correlation_id
        ]
        return matching

    def get_spans_by_trace_id(self, trace_id: str) -> list:
        """Get all spans for a trace_id."""
        matching = [
            span for span in self.completed_spans
            if span.get("trace_id") == trace_id
            or span.get("attributes", {}).get("trace_id") == trace_id
        ]
        return matching
    
    def get_saga_trace(self, saga_id: str) -> Dict[str, Any]:
        """
        Get full trace for a saga.
        
        Args:
            saga_id: The saga ID to trace
        
        Returns:
            Trace tree showing all spans and relationships
        """
        spans = [
            span for span in self.completed_spans
            if span.get("attributes", {}).get("saga_id") == saga_id
        ]
        
        # Sort by start time
        spans_sorted = sorted(
            spans,
            key=lambda s: s.get("start_time", "")
        )
        
        if not spans_sorted:
            return {"saga_id": saga_id, "spans": []}
        
        root_span = spans_sorted[0]
        
        return {
            "saga_id": saga_id,
            "correlation_id": root_span.get("attributes", {}).get("correlation_id"),
            "trace_id": root_span.get("trace_id") or root_span.get("attributes", {}).get("trace_id"),
            "flow_name": root_span.get("attributes", {}).get("flow_name"),
            "status": root_span.get("status"),
            "total_duration_ms": root_span.get("duration_ms", 0),
            "span_count": len(spans_sorted),
            "spans": spans_sorted,
        }
    
    # =====================================================================
    # Health and Stats
    # =====================================================================
    
    def get_telemetry_stats(self) -> Dict[str, Any]:
        """Get telemetry collector statistics."""
        return {
            "service_name": self.service_name,
            "active_spans": len(self.active_spans),
            "completed_spans": len(self.completed_spans),
            "otlp_endpoint": self.otlp_endpoint,
        }
    
    # =====================================================================
    # OpenTelemetry Integration Template
    # =====================================================================
    
    def setup_real_otel(self):
        """
        Setup real OpenTelemetry exporters (template).
        
        Call this to enable real OTLP export instead of in-memory storage.
        Requires: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp
        """
        try:
            from opentelemetry import trace, metrics
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            
            resource = Resource(attributes={
                SERVICE_NAME: self.service_name
            })
            
            otlp_exporter = OTLPSpanExporter(
                endpoint=self.otlp_endpoint,
            )
            
            trace_provider = TracerProvider(resource=resource)
            trace_provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            trace.set_tracer_provider(trace_provider)
            
            logger.info("✅ Real OpenTelemetry exporters configured")
            logger.info(f"   Endpoint: {self.otlp_endpoint}")
            
        except ImportError as e:
            logger.warning(
                f"⚠️  OpenTelemetry libraries not installed: {e}\n"
                f"   Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
            )
