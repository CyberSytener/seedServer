"""
Metrics instrumentation for Seed Server
Provides StatsD-based metrics collection for LLM pipeline monitoring
"""

import time
import logging
from functools import wraps
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from app.settings import get_settings

logger = logging.getLogger(__name__)

# Metrics client (will be initialized at startup)
_metrics_client = None


class StatsdClientAdapter:
    """
    Adapter that normalizes statsd client method names across implementations.

    python-statsd exposes `incr`, while some call-sites use `increment`.
    """

    def __init__(self, client):
        self._client = client
        # Preserve socket handle used by shutdown_metrics().
        self._sock = getattr(client, "_sock", None)

    def timing(self, stat, value, rate=1):
        return self._client.timing(stat, value, rate=rate)

    def increment(self, stat, count=1, rate=1):
        if hasattr(self._client, "increment"):
            return self._client.increment(stat, count=count, rate=rate)
        if hasattr(self._client, "incr"):
            return self._client.incr(stat, count=count, rate=rate)
        return None

    def gauge(self, stat, value, rate=1):
        return self._client.gauge(stat, value, rate=rate)

    def histogram(self, stat, value, rate=1):
        if hasattr(self._client, "histogram"):
            return self._client.histogram(stat, value, rate=rate)
        # Fallback: emit as timing to avoid dropping observability entirely.
        return self._client.timing(stat, value, rate=rate)


class MetricType(Enum):
    """Metric types"""
    GAUGE = "gauge"
    COUNTER = "counter"
    TIMER = "timer"
    HISTOGRAM = "histogram"


def init_metrics(host: str = "localhost", port: int = 8125, prefix: str = "seed_server"):
    """Initialize metrics client.

    The ``statsd`` package dependency has been removed.  This function now
    always falls back to :class:`NoOpMetrics`.  If you need StatsD again,
    re-add ``statsd`` to *pyproject.toml* and uncomment the import below.
    """
    global _metrics_client
    if _metrics_client is not None:
        shutdown_metrics()
    logger.info(
        "StatsD dependency removed — running in no-op metrics mode "
        "(host=%s, port=%s, prefix=%s)",
        host, port, prefix,
    )
    _metrics_client = NoOpMetrics()


def shutdown_metrics() -> None:
    """Shutdown metrics client and close underlying resources if present."""
    global _metrics_client
    client = _metrics_client
    _metrics_client = None

    if client is None:
        return

    try:
        sock = getattr(client, "_sock", None)
        if sock is not None and hasattr(sock, "close"):
            sock.close()
    except Exception as e:
        logger.debug(f"Failed to close metrics socket cleanly: {e}")


class NoOpMetrics:
    """No-op metrics client (fallback when StatsD unavailable)"""
    def timing(self, stat, value, rate=1): pass
    def increment(self, stat, count=1, rate=1): pass
    def gauge(self, stat, value, rate=1): pass
    def histogram(self, stat, value, rate=1): pass


def get_metrics():
    """Get global metrics client"""
    global _metrics_client
    if _metrics_client is None:
        if get_settings().metrics_enabled:
            init_metrics()
        else:
            _metrics_client = NoOpMetrics()
    return _metrics_client


# ============================================================================
# Pipeline Metrics
# ============================================================================

class PipelineMetrics:
    """Pipeline execution metrics"""
    
    @staticmethod
    def record_step_latency(step_name: str, duration_ms: float, success: bool = True, **tags):
        """Record step execution time"""
        metrics = get_metrics()
        status = "success" if success else "error"
        stat_name = f"pipeline.step.latency.{step_name}.{status}"
        metrics.timing(stat_name, duration_ms)
        
        logger.debug(f"[METRIC] {step_name}: {duration_ms:.0f}ms ({status})")
    
    @staticmethod
    def record_step_result(step_name: str, success: bool, **tags):
        """Record step result (success/failure)"""
        metrics = get_metrics()
        result = "success" if success else "failure"
        stat_name = f"pipeline.step.result.{step_name}.{result}"
        metrics.increment(stat_name, 1)
    
    @staticmethod
    def record_pipeline_completion(mode: str, duration_ms: float, score: float):
        """Record full pipeline completion"""
        metrics = get_metrics()
        metrics.timing(f"pipeline.total.latency.{mode}", duration_ms)
        metrics.gauge(f"pipeline.quality.score.{mode}", score)
    
    @staticmethod
    def record_exercise_count(mode: str, count: int):
        """Record number of exercises generated"""
        metrics = get_metrics()
        metrics.gauge(f"pipeline.exercises.count.{mode}", count)
    
    @staticmethod
    def record_validation_score(mode: str, score: float):
        """Record validation score"""
        metrics = get_metrics()
        metrics.gauge(f"validation.score.{mode}", score)


# ============================================================================
# LLM Client Metrics
# ============================================================================

class LLMMetrics:
    """LLM API call metrics"""
    
    @staticmethod
    def record_api_call(model_name: str, duration_ms: float, success: bool = True, tokens_used: Optional[int] = None):
        """Record LLM API call"""
        metrics = get_metrics()
        status = "success" if success else "error"
        
        # Latency by model
        metrics.timing(f"llm.api.latency.{model_name}", duration_ms)
        
        # Overall API latency
        metrics.timing(f"llm.api.latency.overall", duration_ms)
        
        # Success/failure count
        metrics.increment(f"llm.api.calls.{model_name}.{status}", 1)
        
        # Token usage if available
        if tokens_used:
            metrics.gauge(f"llm.tokens.{model_name}", tokens_used)
        
        logger.debug(f"[LLM] {model_name}: {duration_ms:.0f}ms ({status})")
    
    @staticmethod
    def record_retry(model_name: str, attempt: int, reason: str):
        """Record LLM retry"""
        metrics = get_metrics()
        metrics.increment(f"llm.retries.{model_name}.{reason}", 1)
        logger.info(f"[LLM RETRY] {model_name} attempt {attempt}: {reason}")
    
    @staticmethod
    def record_parse_error(step_name: str, error_type: str):
        """Record JSON parse error"""
        metrics = get_metrics()
        metrics.increment(f"llm.parse_errors.{step_name}.{error_type}", 1)
        logger.warning(f"[PARSE ERROR] {step_name}: {error_type}")
    
    @staticmethod
    def record_repair_applied(step_name: str, repair_type: str):
        """Record when repair function was applied"""
        metrics = get_metrics()
        metrics.increment(f"llm.repairs.{step_name}.{repair_type}", 1)
        logger.debug(f"[REPAIR] {step_name}: {repair_type}")


# ============================================================================
# Queue Metrics
# ============================================================================

class QueueMetrics:
    """Job queue metrics"""
    
    @staticmethod
    def record_queue_depth(queue_name: str, depth: int):
        """Record current queue depth"""
        metrics = get_metrics()
        metrics.gauge(f"queue.depth.{queue_name}", depth)
    
    @staticmethod
    def record_job_duration(queue_name: str, duration_ms: float, status: str):
        """Record job processing time"""
        metrics = get_metrics()
        metrics.timing(f"queue.job.latency.{queue_name}.{status}", duration_ms)
    
    @staticmethod
    def record_job_result(queue_name: str, status: str):
        """Record job result"""
        metrics = get_metrics()
        metrics.increment(f"queue.jobs.{queue_name}.{status}", 1)


# ============================================================================
# HTTP Endpoint Metrics
# ============================================================================

class EndpointMetrics:
    """HTTP endpoint metrics"""
    
    @staticmethod
    def record_request(endpoint: str, method: str, status_code: int, duration_ms: float):
        """Record HTTP request"""
        metrics = get_metrics()
        metrics.timing(f"http.request.latency.{endpoint}.{method}", duration_ms)
        metrics.increment(f"http.requests.{endpoint}.{status_code}", 1)
    
    @staticmethod
    def record_request_error(endpoint: str, method: str, error_type: str):
        """Record HTTP request error"""
        metrics = get_metrics()
        metrics.increment(f"http.errors.{endpoint}.{error_type}", 1)


class BillingMetrics:
    """Credit/billing metrics helpers."""

    @staticmethod
    def record_credit_ledger_event(event: Dict[str, Any]):
        metrics = get_metrics()
        provider = str(event.get("provider") or "unknown")
        model = str(event.get("model") or "unknown")
        stage = str(event.get("stage") or "unknown")
        credits_charged = int(event.get("credits_charged") or 0)
        estimated_cost = float(event.get("estimated_cost_usd") or 0.0)
        usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
        total_tokens = int(usage.get("total_tokens") or 0)

        metrics.increment(f"billing.ledger.events.{provider}.{stage}", 1)
        metrics.gauge(f"billing.credits.{provider}.{model}", credits_charged)
        metrics.gauge(f"billing.tokens.{provider}.{model}", total_tokens)
        metrics.gauge(f"billing.cost_usd.{provider}.{model}", estimated_cost)

        logger.info(
            "[BILLING] ledger event emitted",
            extra={
                "provider": provider,
                "model": model,
                "stage": stage,
                "credits_charged": credits_charged,
                "estimated_cost_usd": estimated_cost,
                "total_tokens": total_tokens,
            },
        )


# ============================================================================
# Decorators for easy instrumentation
# ============================================================================

def track_latency(metric_name: str, tag_field: Optional[str] = None):
    """Decorator to track function latency"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.time() - start) * 1000
                metrics = get_metrics()
                metrics.timing(metric_name, elapsed_ms)
                return result
            except Exception as e:
                elapsed_ms = (time.time() - start) * 1000
                metrics = get_metrics()
                metrics.timing(f"{metric_name}.error", elapsed_ms)
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.time() - start) * 1000
                metrics = get_metrics()
                metrics.timing(metric_name, elapsed_ms)
                return result
            except Exception as e:
                elapsed_ms = (time.time() - start) * 1000
                metrics = get_metrics()
                metrics.timing(f"{metric_name}.error", elapsed_ms)
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


def track_counter(metric_name: str, increment: int = 1):
    """Decorator to track function calls"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            metrics = get_metrics()
            metrics.increment(metric_name, increment)
            return await func(*args, **kwargs)
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            metrics = get_metrics()
            metrics.increment(metric_name, increment)
            return func(*args, **kwargs)
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


# ============================================================================
# Context managers for instrumentation
# ============================================================================

class MetricContext:
    """Context manager for metrics"""
    
    def __init__(self, metric_name: str, metric_type: MetricType = MetricType.TIMER):
        self.metric_name = metric_name
        self.metric_type = metric_type
        self.start_time = None
        self.metrics = get_metrics()
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.time() - self.start_time) * 1000
        
        if self.metric_type == MetricType.TIMER:
            self.metrics.timing(self.metric_name, elapsed_ms)
        elif self.metric_type == MetricType.HISTOGRAM:
            self.metrics.histogram(self.metric_name, elapsed_ms)
        
        if exc_type:
            self.metrics.increment(f"{self.metric_name}.errors", 1)


import asyncio
