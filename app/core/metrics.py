from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# HTTP
HTTP_REQUESTS = Counter(
    "seed_http_requests_total",
    "HTTP requests",
    labelnames=["path", "method", "status"],
)
HTTP_LATENCY = Histogram(
    "seed_http_request_latency_seconds",
    "HTTP request latency",
    labelnames=["path", "method"],
)

# Jobs
JOBS_CREATED = Counter(
    "seed_jobs_created_total",
    "Jobs created",
    labelnames=["mode", "queue"],
)
JOBS_FINISHED = Counter(
    "seed_jobs_finished_total",
    "Jobs finished",
    labelnames=["status", "queue"],
)
QUEUE_DEPTH = Gauge(
    "seed_queue_depth",
    "Queue depth",
    labelnames=["queue"],
)
SCHEDULED_DEPTH = Gauge(
    "seed_scheduled_depth",
    "Scheduled queue depth",
)

# Idempotency
IDEMPOTENCY_HITS = Counter(
    "seed_idempotency_hits_total",
    "Idempotency cache hits",
    labelnames=["store"],
)
IDEMPOTENCY_MISSES = Counter(
    "seed_idempotency_misses_total",
    "Idempotency cache misses",
    labelnames=["store"],
)

# DLQ maintenance
DLQ_MAINTENANCE_CYCLES = Counter(
    "seed_dlq_maintenance_cycles_total",
    "DLQ maintenance cycles executed",
    labelnames=["status"],
)
DLQ_MAINTENANCE_ELIGIBLE = Gauge(
    "seed_dlq_maintenance_eligible",
    "Eligible DLQ records detected in last maintenance cycle",
)
DLQ_MAINTENANCE_TRIAGED_TOTAL = Counter(
    "seed_dlq_maintenance_triaged_total",
    "DLQ records triaged by maintenance",
)
DLQ_MAINTENANCE_PURGED_TOTAL = Counter(
    "seed_dlq_maintenance_purged_total",
    "DLQ records purged by maintenance",
)
DLQ_MAINTENANCE_ALERTS_TOTAL = Counter(
    "seed_dlq_maintenance_alerts_total",
    "DLQ maintenance alert events",
    labelnames=["reason"],
)

# Auth
AUTH_FAILURES = Counter(
    "seed_auth_failures_total",
    "Authentication/authorisation failures",
    labelnames=["reason"],
)
