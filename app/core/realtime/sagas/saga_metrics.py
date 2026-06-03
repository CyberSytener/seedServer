"""
Prometheus metrics for Saga Orchestrator.

Exports metrics for monitoring, alerting, and observability.
"""

import time
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass

try:
    from prometheus_client import Counter, Histogram, Gauge
except Exception:  # pragma: no cover - optional dependency
    Counter = Histogram = Gauge = None

logger = logging.getLogger(__name__)


# =========================================================================
# Prometheus Metrics (shared registry)
# =========================================================================

if Counter and Histogram and Gauge:
    SAGAS_STARTED_TOTAL = Counter(
        "sagas_started_total",
        "Total sagas started",
    )
    SAGAS_FAILED_TOTAL = Counter(
        "sagas_failed_total",
        "Total sagas failed",
    )
    ADAPTER_CALLS_TOTAL = Counter(
        "adapter_calls_total",
        "Total adapter calls",
        ["adapter", "operation", "status"],
    )
    SAGA_DURATION_SECONDS = Histogram(
        "saga_duration_seconds",
        "Saga duration in seconds",
        buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600),
    )
    ADAPTER_LATENCY_SECONDS = Histogram(
        "adapter_latency_seconds",
        "Adapter latency in seconds",
        ["adapter", "operation"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
    )
    ACTIVE_SAGAS_COUNT = Gauge(
        "active_sagas_count",
        "Current number of active sagas",
    )
    CIRCUIT_BREAKER_STATE = Gauge(
        "circuit_breaker_state",
        "Circuit breaker state (0=closed, 1=open)",
        ["adapter"],
    )
else:
    SAGAS_STARTED_TOTAL = None
    SAGAS_FAILED_TOTAL = None
    ADAPTER_CALLS_TOTAL = None
    SAGA_DURATION_SECONDS = None
    ADAPTER_LATENCY_SECONDS = None
    ACTIVE_SAGAS_COUNT = None
    CIRCUIT_BREAKER_STATE = None


class PrometheusSagaMetrics:
    """Prometheus-backed metrics for saga orchestrator."""

    def __init__(self):
        self.enabled = Counter is not None

    def record_saga_started(self) -> None:
        if SAGAS_STARTED_TOTAL:
            SAGAS_STARTED_TOTAL.inc()

    def record_saga_failed(self) -> None:
        if SAGAS_FAILED_TOTAL:
            SAGAS_FAILED_TOTAL.inc()

    def record_adapter_call(self, adapter: str, operation: str, status: str) -> None:
        if ADAPTER_CALLS_TOTAL:
            ADAPTER_CALLS_TOTAL.labels(adapter=adapter, operation=operation, status=status).inc()

    def observe_saga_duration(self, duration_seconds: float) -> None:
        if SAGA_DURATION_SECONDS:
            SAGA_DURATION_SECONDS.observe(duration_seconds)

    def observe_adapter_latency(self, adapter: str, operation: str, duration_seconds: float) -> None:
        if ADAPTER_LATENCY_SECONDS:
            ADAPTER_LATENCY_SECONDS.labels(adapter=adapter, operation=operation).observe(duration_seconds)

    def set_active_sagas_count(self, count: int) -> None:
        if ACTIVE_SAGAS_COUNT:
            ACTIVE_SAGAS_COUNT.set(count)

    def set_circuit_breaker_state(self, adapter: str, is_open: bool) -> None:
        if CIRCUIT_BREAKER_STATE:
            CIRCUIT_BREAKER_STATE.labels(adapter=adapter).set(1 if is_open else 0)


# =========================================================================
# Prometheus Metrics Registry (in-memory, exportable to Prometheus)
# =========================================================================

@dataclass
class SagaMetrics:
    """Saga metrics collected over time."""
    
    # Saga lifecycle counters
    sagas_started_total: int = 0
    sagas_succeeded_total: int = 0
    sagas_failed_total: int = 0
    sagas_compensated_total: int = 0
    
    # Timing histograms (milliseconds)
    saga_duration_ms: list = None  # Will track individual durations
    saga_reserve_duration_ms: list = None
    saga_confirm_duration_ms: list = None
    saga_compensation_duration_ms: list = None
    
    # Error tracking
    adapter_errors_total: Dict[str, int] = None
    circuit_breaker_opens_total: int = 0
    lock_contentions_total: int = 0
    timeout_events_total: int = 0
    
    # Resource usage
    active_sagas_count: int = 0
    idempotency_cache_size: int = 0
    compensation_queue_size: int = 0
    dlq_size: int = 0
    
    # Rate limiting
    rate_limit_rejections_total: int = 0
    
    # Critical alerting metrics
    circuit_breaker_open_duration_ms: Dict[str, float] = None  # Per adapter
    lock_contention_wait_time_ms: list = None  # Individual wait times
    compensation_triggered_total: int = 0  # Sagas requiring compensation
    def __post_init__(self):
        if self.saga_duration_ms is None:
            self.saga_duration_ms = []
        if self.saga_reserve_duration_ms is None:
            self.saga_reserve_duration_ms = []
        if self.saga_confirm_duration_ms is None:
            self.saga_confirm_duration_ms = []
        if self.saga_compensation_duration_ms is None:
            self.saga_compensation_duration_ms = []
        if self.adapter_errors_total is None:
            self.adapter_errors_total = {}
        if self.circuit_breaker_open_duration_ms is None:
            self.circuit_breaker_open_duration_ms = {}
        if self.lock_contention_wait_time_ms is None:
            self.lock_contention_wait_time_ms = []


class SagaMetricsCollector:
    """Collects and exports Saga metrics."""
    
    def __init__(self, max_histogram_size: int = 1000):
        self.metrics = SagaMetrics()
        self.max_histogram_size = max_histogram_size
        self.start_time = datetime.now(timezone.utc)
    
    # =====================================================================
    # Saga Lifecycle Metrics
    # =====================================================================
    
    def record_saga_started(self):
        """Record a saga started event."""
        self.metrics.sagas_started_total += 1
    
    def record_saga_succeeded(self):
        """Record a saga succeeded event."""
        self.metrics.sagas_succeeded_total += 1
    
    def record_saga_failed(self):
        """Record a saga failed event."""
        self.metrics.sagas_failed_total += 1
    
    def record_saga_compensated(self):
        """Record a saga compensation event."""
        self.metrics.sagas_compensated_total += 1
    
    # =====================================================================
    # Timing Metrics
    # =====================================================================
    
    def record_saga_duration(self, duration_ms: float):
        """Record saga total execution time."""
        self._add_to_histogram(self.metrics.saga_duration_ms, duration_ms)
    
    def record_reserve_duration(self, duration_ms: float):
        """Record reserve step duration."""
        self._add_to_histogram(self.metrics.saga_reserve_duration_ms, duration_ms)
    
    def record_confirm_duration(self, duration_ms: float):
        """Record confirm step duration."""
        self._add_to_histogram(self.metrics.saga_confirm_duration_ms, duration_ms)
    
    def record_compensation_duration(self, duration_ms: float):
        """Record compensation execution time."""
        self._add_to_histogram(self.metrics.saga_compensation_duration_ms, duration_ms)
    
    def _add_to_histogram(self, histogram: list, value: float):
        """Add value to histogram with size limit."""
        if len(histogram) >= self.max_histogram_size:
            # Remove oldest if at max size
            histogram.pop(0)
        histogram.append(value)
    
    # =====================================================================
    # Error Metrics
    # =====================================================================
    
    def record_adapter_error(self, adapter_name: str, error_type: str = "unknown"):
        """Record adapter error by name and type."""
        key = f"{adapter_name}:{error_type}"
        self.metrics.adapter_errors_total[key] = self.metrics.adapter_errors_total.get(key, 0) + 1
    
    def record_circuit_breaker_open(self, adapter_name: str):
        """Record circuit breaker opening."""
        self.metrics.circuit_breaker_opens_total += 1
        logger.warning(f"📊 Circuit breaker OPEN for {adapter_name}")
    
    def record_lock_contention(self):
        """Record lock contention event."""
        self.metrics.lock_contentions_total += 1
    
    def record_timeout_event(self):
        """Record timeout event."""
        self.metrics.timeout_events_total += 1
    
    # =====================================================================
    # Resource Metrics
    # =====================================================================
    
    def set_active_sagas_count(self, count: int):
        """Set current active saga count."""
        self.metrics.active_sagas_count = count
    
    def set_idempotency_cache_size(self, size: int):
        """Set idempotency cache size."""
        self.metrics.idempotency_cache_size = size
    
    def set_compensation_queue_size(self, size: int):
        """Set compensation queue size."""
        self.metrics.compensation_queue_size = size
    
    def set_dlq_size(self, size: int):
        """Set dead letter queue size."""
        self.metrics.dlq_size = size
    
    # =====================================================================
    # Rate Limiting Metrics
    # =====================================================================
    
    def record_rate_limit_rejection(self):
        """Record rate limit rejection."""
        self.metrics.rate_limit_rejections_total += 1
    
    # =====================================================================
    # Critical Alerting Metrics
    # =====================================================================
    
    def record_circuit_breaker_open_duration(self, adapter_name: str, duration_ms: float):
        """Record how long circuit breaker was open."""
        if adapter_name not in self.metrics.circuit_breaker_open_duration_ms:
            self.metrics.circuit_breaker_open_duration_ms[adapter_name] = 0
        self.metrics.circuit_breaker_open_duration_ms[adapter_name] = duration_ms
    
    def record_lock_contention_wait_time(self, wait_time_ms: float):
        """Record lock acquisition wait time."""
        self._add_to_histogram(self.metrics.lock_contention_wait_time_ms, wait_time_ms)
        if wait_time_ms > 5000:  # Alert on long waits
            logger.warning(f"⚠️  High lock contention: {wait_time_ms:.0f}ms wait time")
    
    def record_compensation_triggered(self):
        """Record that compensation was triggered for a saga."""
        self.metrics.compensation_triggered_total += 1
    
    # =====================================================================
    # Critical Metrics Calculations
    # =====================================================================
    
    def get_success_rate(self) -> float:
        """Calculate saga success rate percentage."""
        if self.metrics.sagas_started_total == 0:
            return 100.0
        return (self.metrics.sagas_succeeded_total / self.metrics.sagas_started_total) * 100
    
    def get_failure_rate(self) -> float:
        """Calculate saga failure rate percentage."""
        if self.metrics.sagas_started_total == 0:
            return 0.0
        return (self.metrics.sagas_failed_total / self.metrics.sagas_started_total) * 100
    
    def get_compensation_rate(self) -> float:
        """Calculate compensation rate percentage."""
        if self.metrics.sagas_started_total == 0:
            return 0.0
        return (self.metrics.compensation_triggered_total / self.metrics.sagas_started_total) * 100
    
    def get_average_saga_duration(self) -> float:
        """Get average saga execution time in milliseconds."""
        if not self.metrics.saga_duration_ms:
            return 0.0
        return sum(self.metrics.saga_duration_ms) / len(self.metrics.saga_duration_ms)
    
    def get_average_lock_wait_time(self) -> float:
        """Get average lock acquisition wait time."""
        if not self.metrics.lock_contention_wait_time_ms:
            return 0.0
        return sum(self.metrics.lock_contention_wait_time_ms) / len(self.metrics.lock_contention_wait_time_ms)
    
    def get_max_lock_wait_time(self) -> float:
        """Get maximum lock acquisition wait time (P99)."""
        if not self.metrics.lock_contention_wait_time_ms:
            return 0.0
        return max(self.metrics.lock_contention_wait_time_ms)
    
    def get_circuit_breaker_status(self) -> Dict[str, Any]:
        """Get circuit breaker status for all adapters."""
        return {
            "open_adapters": [
                {
                    "adapter": adapter,
                    "open_duration_ms": duration
                }
                for adapter, duration in self.metrics.circuit_breaker_open_duration_ms.items()
                if duration > 0
            ],
            "total_opens": self.metrics.circuit_breaker_opens_total,
        }
    
    # =====================================================================
    # Prometheus Export Format
    # =====================================================================
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        uptime_seconds = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        # HELP and TYPE declarations
        lines.append("# HELP saga_uptime_seconds Saga system uptime")
        lines.append("# TYPE saga_uptime_seconds counter")
        lines.append(f"saga_uptime_seconds {uptime_seconds}\n")
        
        lines.append("# HELP sagas_started_total Total sagas started")
        lines.append("# TYPE sagas_started_total counter")
        lines.append(f"sagas_started_total {self.metrics.sagas_started_total}\n")
        
        lines.append("# HELP sagas_succeeded_total Total sagas succeeded")
        lines.append("# TYPE sagas_succeeded_total counter")
        lines.append(f"sagas_succeeded_total {self.metrics.sagas_succeeded_total}\n")
        
        lines.append("# HELP sagas_failed_total Total sagas failed")
        lines.append("# TYPE sagas_failed_total counter")
        lines.append(f"sagas_failed_total {self.metrics.sagas_failed_total}\n")
        
        lines.append("# HELP sagas_compensated_total Total sagas compensated")
        lines.append("# TYPE sagas_compensated_total counter")
        lines.append(f"sagas_compensated_total {self.metrics.sagas_compensated_total}\n")
        
        # Success/failure rates
        if self.metrics.sagas_started_total > 0:
            success_rate = (self.metrics.sagas_succeeded_total / self.metrics.sagas_started_total) * 100
            failure_rate = (self.metrics.sagas_failed_total / self.metrics.sagas_started_total) * 100
            compensation_rate = (self.metrics.sagas_compensated_total / self.metrics.sagas_started_total) * 100
            
            lines.append("# HELP saga_success_rate_percent Success rate percentage")
            lines.append("# TYPE saga_success_rate_percent gauge")
            lines.append(f"saga_success_rate_percent {success_rate:.2f}\n")
            
            lines.append("# HELP saga_failure_rate_percent Failure rate percentage")
            lines.append("# TYPE saga_failure_rate_percent gauge")
            lines.append(f"saga_failure_rate_percent {failure_rate:.2f}\n")
            
            lines.append("# HELP saga_compensation_rate_percent Compensation rate percentage")
            lines.append("# TYPE saga_compensation_rate_percent gauge")
            lines.append(f"saga_compensation_rate_percent {compensation_rate:.2f}\n")
        
        # Timing histograms (P50, P95, P99)
        if self.metrics.saga_duration_ms:
            p50, p95, p99 = self._calculate_percentiles(self.metrics.saga_duration_ms)
            lines.append("# HELP saga_duration_ms_p50 Saga duration 50th percentile")
            lines.append("# TYPE saga_duration_ms_p50 gauge")
            lines.append(f"saga_duration_ms_p50 {p50:.2f}\n")
            
            lines.append("# HELP saga_duration_ms_p95 Saga duration 95th percentile")
            lines.append("# TYPE saga_duration_ms_p95 gauge")
            lines.append(f"saga_duration_ms_p95 {p95:.2f}\n")
            
            lines.append("# HELP saga_duration_ms_p99 Saga duration 99th percentile")
            lines.append("# TYPE saga_duration_ms_p99 gauge")
            lines.append(f"saga_duration_ms_p99 {p99:.2f}\n")
        
        # Critical alerting metrics
        lines.append("# HELP saga_average_duration_ms Average saga execution time in milliseconds")
        lines.append("# TYPE saga_average_duration_ms gauge")
        avg_duration = self.get_average_saga_duration()
        lines.append(f"saga_average_duration_ms {avg_duration:.2f}\n")
        
        lines.append("# HELP saga_success_rate_threshold_ok Whether success rate is above 90%")
        lines.append("# TYPE saga_success_rate_threshold_ok gauge")
        success_rate_ok = 1 if self.get_success_rate() >= 90 else 0
        lines.append(f"saga_success_rate_threshold_ok {success_rate_ok}\n")
        
        lines.append("# HELP saga_failure_rate_threshold_ok Whether failure rate is below 10%")
        lines.append("# TYPE saga_failure_rate_threshold_ok gauge")
        failure_rate_ok = 1 if self.get_failure_rate() <= 10 else 0
        lines.append(f"saga_failure_rate_threshold_ok {failure_rate_ok}\n")
        
        lines.append("# HELP saga_compensation_rate_threshold_ok Whether compensation rate is below 5%")
        lines.append("# TYPE saga_compensation_rate_threshold_ok gauge")
        comp_rate = self.get_compensation_rate()
        comp_rate_ok = 1 if comp_rate <= 5 else 0
        lines.append(f"saga_compensation_rate_threshold_ok {comp_rate_ok}\n")
        
        lines.append("# HELP saga_lock_contention_wait_avg_ms Average lock contention wait time")
        lines.append("# TYPE saga_lock_contention_wait_avg_ms gauge")
        avg_lock_wait = self.get_average_lock_wait_time()
        lines.append(f"saga_lock_contention_wait_avg_ms {avg_lock_wait:.2f}\n")
        
        lines.append("# HELP saga_lock_contention_wait_p99_ms P99 lock contention wait time")
        lines.append("# TYPE saga_lock_contention_wait_p99_ms gauge")
        max_lock_wait = self.get_max_lock_wait_time()
        lock_wait_ok = 1 if max_lock_wait <= 5000 else 0
        lines.append(f"saga_lock_contention_wait_p99_ms {max_lock_wait:.2f}\n")
        lines.append(f"# HELP saga_lock_contention_threshold_ok Whether P99 lock wait is below 5000ms")
        lines.append(f"# TYPE saga_lock_contention_threshold_ok gauge")
        lines.append(f"saga_lock_contention_threshold_ok {lock_wait_ok}\n")
        
        lines.append("# HELP saga_circuit_breaker_open Circuit breaker open for adapter")
        lines.append("# TYPE saga_circuit_breaker_open gauge")
        cb_status = self.get_circuit_breaker_status()
        for adapter_name, (is_open, total_opens) in cb_status.items():
            is_open_val = 1 if is_open else 0
            lines.append(f'saga_circuit_breaker_open{{adapter="{adapter_name}"}} {is_open_val}')
        lines.append("")
        
        lines.append("# HELP saga_circuit_breaker_open_count Circuit breaker open count by adapter")
        lines.append("# TYPE saga_circuit_breaker_open_count counter")
        for adapter_name, duration_ms in self.metrics.circuit_breaker_open_duration_ms.items():
            open_count = len(duration_ms) if isinstance(duration_ms, list) else 1
            lines.append(f'saga_circuit_breaker_open_count{{adapter="{adapter_name}"}} {open_count}')
        lines.append("")
        
        # Error metrics
        lines.append("# HELP adapter_errors_total Total adapter errors by type")
        lines.append("# TYPE adapter_errors_total counter")
        for error_key, count in self.metrics.adapter_errors_total.items():
            adapter, error_type = error_key.split(":", 1)
            lines.append(f'adapter_errors_total{{adapter="{adapter}",error="{error_type}"}} {count}')
        lines.append("")
        
        lines.append("# HELP circuit_breaker_opens_total Total circuit breaker opens")
        lines.append("# TYPE circuit_breaker_opens_total counter")
        lines.append(f"circuit_breaker_opens_total {self.metrics.circuit_breaker_opens_total}\n")
        
        lines.append("# HELP lock_contentions_total Total lock contention events")
        lines.append("# TYPE lock_contentions_total counter")
        lines.append(f"lock_contentions_total {self.metrics.lock_contentions_total}\n")
        
        lines.append("# HELP timeout_events_total Total timeout events")
        lines.append("# TYPE timeout_events_total counter")
        lines.append(f"timeout_events_total {self.metrics.timeout_events_total}\n")
        
        # Resource metrics
        lines.append("# HELP active_sagas_count Current number of active sagas")
        lines.append("# TYPE active_sagas_count gauge")
        lines.append(f"active_sagas_count {self.metrics.active_sagas_count}\n")
        
        lines.append("# HELP idempotency_cache_size Idempotency cache size")
        lines.append("# TYPE idempotency_cache_size gauge")
        lines.append(f"idempotency_cache_size {self.metrics.idempotency_cache_size}\n")
        
        lines.append("# HELP dlq_size Dead letter queue size")
        lines.append("# TYPE dlq_size gauge")
        lines.append(f"dlq_size {self.metrics.dlq_size}\n")
        
        lines.append("# HELP rate_limit_rejections_total Total rate limit rejections")
        lines.append("# TYPE rate_limit_rejections_total counter")
        lines.append(f"rate_limit_rejections_total {self.metrics.rate_limit_rejections_total}\n")
        
        return "\n".join(lines)
    
    def _calculate_percentiles(self, values: list) -> tuple:
        """Calculate P50, P95, P99 from values."""
        if not values:
            return 0, 0, 0
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        p50_idx = max(0, int(n * 0.50) - 1)
        p95_idx = max(0, int(n * 0.95) - 1)
        p99_idx = max(0, int(n * 0.99) - 1)
        
        return (
            sorted_values[p50_idx],
            sorted_values[p95_idx],
            sorted_values[p99_idx]
        )
    
    def get_summary(self) -> Dict[str, Any]:
        """Get metrics summary for logging."""
        total_sagas = self.metrics.sagas_started_total
        success_rate = (self.metrics.sagas_succeeded_total / total_sagas * 100) if total_sagas > 0 else 0
        
        return {
            "uptime": (datetime.now(timezone.utc) - self.start_time).total_seconds(),
            "sagas_started": self.metrics.sagas_started_total,
            "sagas_succeeded": self.metrics.sagas_succeeded_total,
            "sagas_failed": self.metrics.sagas_failed_total,
            "sagas_compensated": self.metrics.sagas_compensated_total,
            "success_rate": f"{success_rate:.1f}%",
            "active_sagas": self.metrics.active_sagas_count,
            "circuit_breaker_opens": self.metrics.circuit_breaker_opens_total,
            "lock_contentions": self.metrics.lock_contentions_total,
            "timeout_events": self.metrics.timeout_events_total,
            "rate_limit_rejections": self.metrics.rate_limit_rejections_total,
            "dlq_size": self.metrics.dlq_size,
        }
