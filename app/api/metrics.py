"""
Performance Metrics API

Provides real-time metrics for monitoring and observability:
- HTTP request latency (TTFB, total)
- LLM generation performance
- Connection pool stats
- Job queue depth
- Resource utilization

Metrics format: Prometheus-compatible text format
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List

from fastapi import APIRouter, Response
from pydantic import BaseModel


router = APIRouter(prefix="/v1/metrics", tags=["Metrics"])


# In-memory metrics storage (simple implementation)
# In production, use Prometheus client or similar
class MetricsStore:
    def __init__(self):
        self.http_requests_total = 0
        self.http_requests_by_status: Dict[int, int] = {}
        self.http_latency_sum = 0.0
        self.http_latency_count = 0
        self.http_latency_buckets = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0]
        self.http_latency_histogram: Dict[float, int] = {b: 0 for b in self.http_latency_buckets}
        
        self.llm_generation_total = 0
        self.llm_generation_sum = 0.0
        self.llm_generation_count = 0
        self.llm_generation_buckets = [1.0, 5.0, 10.0, 20.0, 30.0, 60.0]
        self.llm_generation_histogram: Dict[float, int] = {b: 0 for b in self.llm_generation_buckets}
        
        self.connection_pool_active = 0
        self.connection_pool_idle = 0
        self.connection_pool_max = 100
        
        self.queue_depth: Dict[str, int] = {}
        
        self.start_time = time.time()
    
    def record_http_request(self, status_code: int, duration_seconds: float):
        """Record HTTP request metrics"""
        self.http_requests_total += 1
        self.http_requests_by_status[status_code] = self.http_requests_by_status.get(status_code, 0) + 1
        self.http_latency_sum += duration_seconds
        self.http_latency_count += 1
        
        for bucket in self.http_latency_buckets:
            if duration_seconds <= bucket:
                self.http_latency_histogram[bucket] += 1
    
    def record_llm_generation(self, duration_seconds: float):
        """Record LLM generation metrics"""
        self.llm_generation_total += 1
        self.llm_generation_sum += duration_seconds
        self.llm_generation_count += 1
        
        for bucket in self.llm_generation_buckets:
            if duration_seconds <= bucket:
                self.llm_generation_histogram[bucket] += 1
    
    def update_connection_pool(self, active: int, idle: int):
        """Update connection pool metrics"""
        self.connection_pool_active = active
        self.connection_pool_idle = idle
    
    def update_queue_depth(self, queue_name: str, depth: int):
        """Update queue depth metrics"""
        self.queue_depth[queue_name] = depth
    
    def to_prometheus_format(self) -> str:
        """Export metrics in Prometheus text format"""
        lines = []
        
        # HTTP metrics
        lines.append("# HELP http_requests_total Total number of HTTP requests")
        lines.append("# TYPE http_requests_total counter")
        lines.append(f"http_requests_total {self.http_requests_total}")
        
        lines.append("# HELP http_requests_by_status HTTP requests by status code")
        lines.append("# TYPE http_requests_by_status counter")
        for status, count in self.http_requests_by_status.items():
            lines.append(f'http_requests_by_status{{status="{status}"}} {count}')
        
        lines.append("# HELP http_latency_seconds HTTP request latency")
        lines.append("# TYPE http_latency_seconds histogram")
        cumulative = 0
        for bucket in self.http_latency_buckets:
            cumulative += self.http_latency_histogram[bucket]
            lines.append(f'http_latency_seconds_bucket{{le="{bucket}"}} {cumulative}')
        lines.append(f'http_latency_seconds_bucket{{le="+Inf"}} {self.http_latency_count}')
        lines.append(f'http_latency_seconds_sum {self.http_latency_sum}')
        lines.append(f'http_latency_seconds_count {self.http_latency_count}')
        
        # LLM metrics
        lines.append("# HELP llm_generation_total Total number of LLM generations")
        lines.append("# TYPE llm_generation_total counter")
        lines.append(f"llm_generation_total {self.llm_generation_total}")
        
        lines.append("# HELP llm_generation_seconds LLM generation duration")
        lines.append("# TYPE llm_generation_seconds histogram")
        cumulative = 0
        for bucket in self.llm_generation_buckets:
            cumulative += self.llm_generation_histogram[bucket]
            lines.append(f'llm_generation_seconds_bucket{{le="{bucket}"}} {cumulative}')
        lines.append(f'llm_generation_seconds_bucket{{le="+Inf"}} {self.llm_generation_count}')
        lines.append(f'llm_generation_seconds_sum {self.llm_generation_sum}')
        lines.append(f'llm_generation_seconds_count {self.llm_generation_count}')
        
        # Connection pool metrics
        lines.append("# HELP connection_pool_active Active connections in pool")
        lines.append("# TYPE connection_pool_active gauge")
        lines.append(f"connection_pool_active {self.connection_pool_active}")
        
        lines.append("# HELP connection_pool_idle Idle connections in pool")
        lines.append("# TYPE connection_pool_idle gauge")
        lines.append(f"connection_pool_idle {self.connection_pool_idle}")
        
        lines.append("# HELP connection_pool_max Maximum connections in pool")
        lines.append("# TYPE connection_pool_max gauge")
        lines.append(f"connection_pool_max {self.connection_pool_max}")
        
        # Queue metrics
        lines.append("# HELP queue_depth Jobs waiting in queue")
        lines.append("# TYPE queue_depth gauge")
        for queue_name, depth in self.queue_depth.items():
            lines.append(f'queue_depth{{queue="{queue_name}"}} {depth}')
        
        # Process metrics
        lines.append("# HELP process_uptime_seconds Process uptime in seconds")
        lines.append("# TYPE process_uptime_seconds gauge")
        lines.append(f"process_uptime_seconds {time.time() - self.start_time}")
        
        return "\n".join(lines) + "\n"


# Global metrics store
_metrics = MetricsStore()


def get_metrics_store() -> MetricsStore:
    """Get global metrics store"""
    return _metrics


class MetricsSummary(BaseModel):
    """Human-readable metrics summary"""
    uptime_seconds: float
    http_requests_total: int
    http_avg_latency_ms: float
    http_requests_by_status: Dict[int, int]
    llm_generations_total: int
    llm_avg_duration_seconds: float
    connection_pool_active: int
    connection_pool_idle: int
    connection_pool_utilization: float
    queue_depths: Dict[str, int]


@router.get("/prometheus", response_class=Response)
async def get_prometheus_metrics():
    """
    Get metrics in Prometheus text format
    
    Use this endpoint with Prometheus scraper:
    ```yaml
    scrape_configs:
      - job_name: 'seed_api'
        static_configs:
          - targets: ['localhost:8000']
        metrics_path: '/v1/metrics/prometheus'
    ```
    """
    metrics_text = _metrics.to_prometheus_format()
    return Response(content=metrics_text, media_type="text/plain")


@router.get("/summary", response_model=MetricsSummary)
async def get_metrics_summary():
    """
    Get human-readable metrics summary
    
    Useful for dashboards and monitoring UIs.
    """
    avg_latency_ms = 0.0
    if _metrics.http_latency_count > 0:
        avg_latency_ms = (_metrics.http_latency_sum / _metrics.http_latency_count) * 1000
    
    avg_llm_duration = 0.0
    if _metrics.llm_generation_count > 0:
        avg_llm_duration = _metrics.llm_generation_sum / _metrics.llm_generation_count
    
    pool_utilization = 0.0
    if _metrics.connection_pool_max > 0:
        pool_utilization = _metrics.connection_pool_active / _metrics.connection_pool_max
    
    return MetricsSummary(
        uptime_seconds=time.time() - _metrics.start_time,
        http_requests_total=_metrics.http_requests_total,
        http_avg_latency_ms=avg_latency_ms,
        http_requests_by_status=_metrics.http_requests_by_status,
        llm_generations_total=_metrics.llm_generation_total,
        llm_avg_duration_seconds=avg_llm_duration,
        connection_pool_active=_metrics.connection_pool_active,
        connection_pool_idle=_metrics.connection_pool_idle,
        connection_pool_utilization=pool_utilization,
        queue_depths=_metrics.queue_depth
    )


@router.get("/health")
async def health_check():
    """
    Simple health check endpoint
    
    Returns 200 if service is healthy.
    Used by load balancers and orchestrators.
    """
    return {
        "status": "healthy",
        "uptime": time.time() - _metrics.start_time,
        "timestamp": time.time()
    }


# Background task to update Redis queue depths
async def update_queue_metrics_background():
    """
    Background task to periodically update queue depth metrics
    
    Should be started on application startup.
    """
    try:
        import redis.asyncio as redis
        import os
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url, decode_responses=True)
        
        while True:
            try:
                # Update queue depths
                for queue_name in ["q_fast", "q_batch", "q_low"]:
                    depth = await redis_client.llen(queue_name)
                    _metrics.update_queue_depth(queue_name, depth)
                
                await asyncio.sleep(5.0)  # Update every 5 seconds
            
            except Exception as e:
                # Log error but don't crash
                import logging
                logging.error(f"Error updating queue metrics: {e}")
                await asyncio.sleep(10.0)
    
    except ImportError:
        # Redis not available, skip queue metrics
        pass
