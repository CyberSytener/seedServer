"""
Observability for STEP 4: OpenTelemetry tracing + metrics.

Correlates traces across:
- ActionRouter (STEP 2)
- WebSocket Gateway (STEP 3)
- Saga Orchestrator (STEP 4)
- Adapters

Exports to: Jaeger (development) or OTEL Collector (production)
"""

import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable
from functools import wraps

try:
    from opentelemetry import trace, metrics
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.exporter.prometheus import PrometheusMetricReader
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
except ImportError:
    trace = None
    metrics = None
    JaegerExporter = None


logger = logging.getLogger(__name__)


class ObservabilityManager:
    """
    Centralized observability: traces + metrics.
    
    Usage:
        obs = ObservabilityManager("my-service", jaeger_host="localhost")
        
        with obs.span("adapter.booking.reserve") as span:
            span.set_attribute("user_id", user_id)
            result = adapter.reserve(payload)
            span.set_attribute("result_status", result["status"])
    """
    
    def __init__(
        self,
        service_name: str,
        jaeger_host: str = "localhost",
        jaeger_port: int = 6831,
    ):
        """
        Initialize OpenTelemetry.
        
        Args:
            service_name: Service name (for traces)
            jaeger_host: Jaeger collector host
            jaeger_port: Jaeger collector port
        """
        self.service_name = service_name
        self.enabled = trace is not None
        
        if not self.enabled:
            logger.warning("🔕 OpenTelemetry not installed, observability disabled")
            return
        
        # Setup Jaeger exporter
        try:
            jaeger_exporter = JaegerExporter(
                agent_host_name=jaeger_host,
                agent_port=jaeger_port,
            )
            
            trace_provider = TracerProvider()
            trace_provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
            trace.set_tracer_provider(trace_provider)
            
            self.tracer = trace.get_tracer(__name__)
            
            logger.info(f"✅ Jaeger exporter initialized: {jaeger_host}:{jaeger_port}")
        
        except Exception as e:
            logger.warning(f"⚠️  Failed to setup Jaeger: {e}, observability may be limited")
            self.enabled = False
    
    def span(
        self,
        span_name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """
        Context manager for creating spans.
        
        Usage:
            with obs.span("adapter.reserve", {"adapter": "booking"}) as span:
                result = adapter.reserve(payload)
        """
        if not self.enabled:
            # Return dummy context manager
            return DummySpan(span_name)
        
        return OTelSpan(self.tracer, span_name, attributes)
    
    def async_span(
        self,
        span_name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        """Async context manager for spans."""
        if not self.enabled:
            return DummyAsyncSpan(span_name)
        
        return OTelAsyncSpan(self.tracer, span_name, attributes)
    
    def trace_decorator(self, span_name: str, attributes: Optional[Dict[str, Any]] = None):
        """
        Decorator for automatic span creation.
        
        Usage:
            @obs.trace_decorator("adapter.confirm")
            def confirm_booking(payload):
                ...
        """
        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                with self.span(span_name, attributes):
                    return func(*args, **kwargs)
            return wrapper
        return decorator


class DummySpan:
    """Dummy span when observability disabled."""
    
    def __init__(self, name):
        self.name = name
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
    
    def set_attribute(self, key, value):
        pass
    
    def add_event(self, event_name, attributes=None):
        pass
    
    def record_exception(self, exception):
        pass


class DummyAsyncSpan:
    """Dummy async span when observability disabled."""
    
    def __init__(self, name):
        self.name = name
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        pass
    
    def set_attribute(self, key, value):
        pass


class OTelSpan:
    """OpenTelemetry span wrapper."""
    
    def __init__(self, tracer, span_name, attributes):
        self.tracer = tracer
        self.span_name = span_name
        self.attributes = attributes or {}
        self.span = None
    
    def __enter__(self):
        self.span = self.tracer.start_span(self.span_name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.span.set_attribute("error", True)
            self.span.set_attribute("error.type", exc_type.__name__)
            self.span.record_exception(exc_val)
        self.span.end()
    
    def set_attribute(self, key, value):
        if self.span:
            self.span.set_attribute(key, value)
    
    def add_event(self, event_name, attributes=None):
        if self.span:
            self.span.add_event(event_name, attributes or {})


class OTelAsyncSpan:
    """OpenTelemetry async span wrapper."""
    
    def __init__(self, tracer, span_name, attributes):
        self.tracer = tracer
        self.span_name = span_name
        self.attributes = attributes or {}
        self.span = None
    
    async def __aenter__(self):
        self.span = self.tracer.start_span(self.span_name)
        for key, value in self.attributes.items():
            self.span.set_attribute(key, value)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.span.set_attribute("error", True)
            self.span.set_attribute("error.type", exc_type.__name__)
            self.span.record_exception(exc_val)
        self.span.end()
    
    def set_attribute(self, key, value):
        if self.span:
            self.span.set_attribute(key, value)


# Instrumentation helpers
def trace_saga_flow(saga_id: str, saga_type: str):
    """Instrumentation point: saga started."""
    if trace:
        span = trace.get_current_span()
        span.set_attribute("saga.id", saga_id)
        span.set_attribute("saga.type", saga_type)


def trace_adapter_call(adapter_type: str, operation: str, attributes: Dict[str, Any] = None):
    """Instrumentation point: adapter called."""
    if trace:
        span = trace.get_current_span()
        span.set_attribute("adapter.type", adapter_type)
        span.set_attribute("adapter.operation", operation)
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(f"adapter.{key}", value)


def trace_confirmation(saga_id: str, user_id: str, result: str):
    """Instrumentation point: confirmation received."""
    if trace:
        span = trace.get_current_span()
        span.set_attribute("confirmation.saga_id", saga_id)
        span.set_attribute("confirmation.user_id", user_id)
        span.set_attribute("confirmation.result", result)


def trace_compensation(saga_id: str, trigger_error: str, status: str):
    """Instrumentation point: compensation started."""
    if trace:
        span = trace.get_current_span()
        span.set_attribute("compensation.saga_id", saga_id)
        span.set_attribute("compensation.trigger_error", trigger_error)
        span.set_attribute("compensation.status", status)


# Global instance
_obs_manager: Optional[ObservabilityManager] = None


def get_obs_manager(service_name: str = "seed-server") -> ObservabilityManager:
    """Lazy initialize observability manager."""
    global _obs_manager
    if _obs_manager is None:
        _obs_manager = ObservabilityManager(service_name)
    return _obs_manager


# Example usage
"""
from observability import get_obs_manager, trace_saga_flow

obs = get_obs_manager()

# In saga_orchestrator.py
async def start_saga(...):
    saga_id = str(uuid.uuid4())
    trace_saga_flow(saga_id, saga_type)
    ...

# In adapter.py
async def reserve(self, payload):
    with obs.span("adapter.reserve", {"adapter": "booking"}) as span:
        span.set_attribute("user_id", payload.get("user_id"))
        result = ... # real API call
        span.set_attribute("result", result["status"])
        return result
"""
