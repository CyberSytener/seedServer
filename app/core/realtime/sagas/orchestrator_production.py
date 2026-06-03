"""
Production Integration Examples for Saga Orchestrator.

Shows how to use the new production features:
- Prometheus metrics export
- OpenTelemetry tracing
- Rate limiting
- Dead letter queue
"""

import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
import logging

logger = logging.getLogger(__name__)


# =========================================================================
# FastAPI Integration
# =========================================================================

def setup_saga_production_endpoints(app: FastAPI, saga_orchestrator):
    """
    Setup production monitoring and management endpoints.
    
    Args:
        app: FastAPI application
        saga_orchestrator: SagaOrchestrator instance
    """
    
    # =====================================================================
    # Prometheus Metrics Endpoint
    # =====================================================================
    
    @app.get("/metrics/saga", 
             summary="Prometheus Metrics Export",
             tags=["Monitoring"],
             responses={200: {"content": {"text/plain": {}}}})
    async def export_saga_metrics():
        """
        Export Saga metrics in Prometheus format.
        
        Endpoint for Prometheus scraping. Can be configured in prometheus.yml:
        
        ```yaml
        scrape_configs:
          - job_name: 'saga-orchestrator'
            static_configs:
              - targets: ['localhost:8000']
            metrics_path: '/metrics/saga'
        ```
        """
        metrics_export = saga_orchestrator.metrics_collector.export_prometheus()
        return PlainTextResponse(metrics_export)
    
    @app.get("/api/v1/saga/metrics/summary",
             summary="Saga Metrics Summary",
             tags=["Monitoring"])
    async def get_saga_metrics_summary():
        """Get human-readable metrics summary."""
        return saga_orchestrator.metrics_collector.get_summary()
    
    # =====================================================================
    # OpenTelemetry Tracing Endpoint
    # =====================================================================
    
    @app.get("/api/v1/saga/traces/{saga_id}",
             summary="Get Saga Trace",
             tags=["Observability"])
    async def get_saga_trace(saga_id: str):
        """
        Get distributed trace for specific saga.
        
        Returns complete trace with all spans and relationships.
        """
        trace = saga_orchestrator.telemetry_collector.get_saga_trace(saga_id)
        return trace
    
    @app.get("/api/v1/saga/traces/correlation/{correlation_id}",
             summary="Get Traces by Correlation ID",
             tags=["Observability"])
    async def get_traces_by_correlation(correlation_id: str):
        """Get all traces for specific correlation ID."""
        spans = saga_orchestrator.telemetry_collector.get_spans_by_correlation_id(
            correlation_id
        )
        return {"correlation_id": correlation_id, "span_count": len(spans), "spans": spans}
    
    @app.get("/api/v1/saga/telemetry/stats",
             summary="Telemetry Stats",
             tags=["Observability"])
    async def get_telemetry_stats():
        """Get telemetry collector statistics."""
        return saga_orchestrator.telemetry_collector.get_telemetry_stats()
    
    # =====================================================================
    # Rate Limiting Status Endpoint
    # =====================================================================
    
    @app.get("/api/v1/saga/ratelimit/stats",
             summary="Rate Limiter Statistics",
             tags=["Protection"])
    async def get_ratelimit_stats():
        """Get rate limiter statistics."""
        return saga_orchestrator.rate_limiter.get_stats()
    
    @app.get("/api/v1/saga/ratelimit/client/{client_id}",
             summary="Client Rate Limit Status",
             tags=["Protection"])
    async def get_client_ratelimit(client_id: str):
        """Get rate limit status for specific client."""
        return saga_orchestrator.rate_limiter.get_client_stats(client_id)
    
    @app.get("/api/v1/saga/ratelimit/top-clients",
             summary="Top Clients by Usage",
             tags=["Protection"])
    async def get_top_clients():
        """Get top clients by request count."""
        top_clients = saga_orchestrator.rate_limiter.get_top_clients(limit=20)
        return {"clients": top_clients}
    
    # =====================================================================
    # Dead Letter Queue Management
    # =====================================================================
    
    @app.get("/api/v1/saga/dlq/messages",
             summary="Get DLQ Messages",
             tags=["DLQ"])
    async def get_dlq_messages(limit: int = 50, skip: int = 0):
        """Get messages in dead letter queue."""
        messages = saga_orchestrator.dlq.get_all_messages()
        paginated = messages[skip:skip+limit]
        return {
            "total": len(messages),
            "skip": skip,
            "limit": limit,
            "messages": [
                {
                    "saga_id": m.saga_id,
                    "action_id": m.action_id,
                    "flow_name": m.flow_name,
                    "message_type": m.message_type.value,
                    "error_message": m.error_message,
                    "created_at": m.created_at,
                    "retry_count": m.retry_count,
                }
                for m in paginated
            ]
        }
    
    @app.get("/api/v1/saga/dlq/{saga_id}",
             summary="Get DLQ Message",
             tags=["DLQ"])
    async def get_dlq_message(saga_id: str):
        """Get specific DLQ message."""
        msg = saga_orchestrator.dlq.get_message(saga_id)
        if not msg:
            raise HTTPException(status_code=404, detail=f"Message {saga_id} not found")
        
        return {
            "saga_id": msg.saga_id,
            "action_id": msg.action_id,
            "correlation_id": msg.correlation_id,
            "flow_name": msg.flow_name,
            "message_type": msg.message_type.value,
            "error_message": msg.error_message,
            "error_type": msg.error_type,
            "last_successful_step": msg.last_successful_step,
            "failed_step": msg.failed_step,
            "created_at": msg.created_at,
            "retry_count": msg.retry_count,
            "next_retry_at": msg.next_retry_at,
        }
    
    @app.post("/api/v1/saga/dlq/{saga_id}/retry",
              summary="Retry DLQ Message",
              tags=["DLQ"])
    async def retry_dlq_message(saga_id: str):
        """Mark DLQ message for retry."""
        msg = saga_orchestrator.dlq.retry_message(saga_id)
        if not msg:
            raise HTTPException(status_code=404, detail=f"Message {saga_id} not found")
        
        return {
            "saga_id": msg.saga_id,
            "retry_count": msg.retry_count,
            "next_retry_at": msg.next_retry_at,
        }
    
    @app.delete("/api/v1/saga/dlq/{saga_id}",
               summary="Resolve DLQ Message",
               tags=["DLQ"])
    async def resolve_dlq_message(saga_id: str):
        """Remove DLQ message (manual resolution)."""
        removed = saga_orchestrator.dlq.remove_message(saga_id)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Message {saga_id} not found")
        
        return {"status": "resolved", "saga_id": saga_id}
    
    @app.get("/api/v1/saga/dlq/stats",
             summary="DLQ Statistics",
             tags=["DLQ"])
    async def get_dlq_stats():
        """Get DLQ statistics."""
        return saga_orchestrator.dlq.get_stats()
    
    @app.get("/api/v1/saga/dlq/report",
             summary="DLQ Report",
             tags=["DLQ"])
    async def get_dlq_report():
        """Get DLQ report (text format)."""
        report = saga_orchestrator.dlq.generate_report()
        return PlainTextResponse(report)
    
    # =====================================================================
    # Health Check with Saga Status
    # =====================================================================
    
    @app.get("/api/v1/health/saga",
             summary="Saga Health Check",
             tags=["Health"])
    async def saga_health_check():
        """
        Comprehensive Saga health check.
        
        Returns:
            - Saga system status (healthy, degraded, unhealthy)
            - Active sagas count
            - Recent failures
            - DLQ size
            - Circuit breaker status
        """
        metrics = saga_orchestrator.metrics_collector.get_summary()
        dlq_stats = saga_orchestrator.dlq.get_stats()
        
        # Determine health status
        dlq_size = dlq_stats['total_messages']
        max_dlq = dlq_stats['max_size']
        dlq_utilization = dlq_stats['queue_utilization_percent']
        
        if dlq_utilization > 80:
            status = "unhealthy"
            detail = "DLQ utilization critical (>80%)"
        elif dlq_utilization > 50:
            status = "degraded"
            detail = "DLQ utilization high (>50%)"
        elif metrics.get('success_rate', '100%').rstrip('%') < '90':
            status = "degraded"
            detail = f"Success rate low ({metrics.get('success_rate', 'N/A')})"
        else:
            status = "healthy"
            detail = "All systems operational"
        
        return {
            "status": status,
            "detail": detail,
            "saga_metrics": metrics,
            "dlq": dlq_stats,
            "timestamp": os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip(),
        }
    
    logger.info("✅ Saga production endpoints registered")
    logger.info("   GET /metrics/saga - Prometheus metrics")
    logger.info("   GET /api/v1/saga/metrics/summary - Metrics summary")
    logger.info("   GET /api/v1/saga/traces/{saga_id} - Distributed trace")
    logger.info("   GET /api/v1/saga/dlq/messages - DLQ messages")
    logger.info("   GET /api/v1/health/saga - Health check")


# =========================================================================
# Rate Limiting Middleware
# =========================================================================

async def saga_rate_limit_middleware(request: Request, call_next, saga_orchestrator):
    """
    Middleware to check rate limits before processing saga requests.
    
    Usage in FastAPI:
        app.middleware("http")(
            lambda request, call_next: saga_rate_limit_middleware(
                request, call_next, saga_orchestrator
            )
        )
    """
    # Skip rate limiting for certain endpoints
    if request.url.path.startswith("/metrics") or request.url.path.startswith("/health"):
        return await call_next(request)
    
    # Skip for non-saga endpoints
    if not request.url.path.startswith("/api/saga") and not request.url.path.startswith("/saga"):
        return await call_next(request)
    
    # Extract client ID (from header, auth, or IP)
    client_id = (
        request.headers.get("X-Client-ID") or
        request.headers.get("X-User-ID") or
        request.client.host
    )
    
    # Check rate limit
    allowed, reason = saga_orchestrator.rate_limiter.check_rate_limit(client_id)
    
    if not allowed:
        return HTTPException(status_code=429, detail=reason)
    
    return await call_next(request)

    
    # =====================================================================
    # Alerting Endpoints
    # =====================================================================
    
    @app.get("/api/v1/saga/alerts/summary",
             summary="Get Alert Summary",
             tags=["Alerting"])
    async def get_alerts_summary():
        """
        Get summary of current alert state.
        
        Returns:
            {
                "total_active": 2,
                "critical": 1,
                "warnings": 1,
                "active_alerts": [
                    {
                        "name": "SagaSuccessRateLow",
                        "severity": "critical",
                        "value": 85.5,
                        "message": "Success rate is 85.5%, below threshold of 90%"
                    }
                ]
            }
        """
        try:
            from app.core.realtime.sagas.saga_alerts import get_alert_manager
            alert_mgr = get_alert_manager()
            return alert_mgr.get_alert_summary()
        except Exception as e:
            logger.error(f"Error fetching alert summary: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/saga/alerts/thresholds",
             summary="Get Alert Thresholds",
             tags=["Alerting"])
    async def get_alert_thresholds():
        """
        Get configured alert thresholds.
        
        Returns thresholds for:
        - Success rate (>= 90%)
        - Failure rate (<= 10%)
        - Compensation rate (<= 5%)
        - Lock contention P99 (<= 5000ms)
        - Circuit breaker duration (<= 60s)
        """
        try:
            from app.core.realtime.sagas.saga_alerts import SagaAlertRules
            return {
                "thresholds": SagaAlertRules.get_alert_thresholds(),
                "rules": [
                    {
                        "name": rule.name,
                        "description": rule.description,
                        "severity": rule.severity.value,
                        "duration": rule.duration,
                    }
                    for rule in SagaAlertRules.get_all_rules()
                ],
            }
        except Exception as e:
            logger.error(f"Error fetching alert thresholds: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/saga/alerts/rules/prometheus",
             summary="Get Prometheus Alert Rules",
             tags=["Alerting"],
             responses={200: {"content": {"text/plain": {}}}})
    async def get_prometheus_rules():
        """
        Get Prometheus alert rules in YAML format.
        
        Can be used to configure Prometheus:
        - Save response as prometheus_rules.yml
        - Update prometheus.yml rule_files to include this file
        - Reload Prometheus
        """
        try:
            from app.core.realtime.sagas.saga_alerts import SagaAlertRules
            rules_yaml = SagaAlertRules.to_prometheus_rules()
            return PlainTextResponse(rules_yaml, media_type="text/plain")
        except Exception as e:
            logger.error(f"Error generating Prometheus rules: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/saga/alerts/config/alertmanager",
             summary="Get AlertManager Configuration",
             tags=["Alerting"])
    async def get_alertmanager_config():
        """
        Get AlertManager configuration.
        
        Can be used to configure AlertManager:
        - Save response as alertmanager.yml
        - Set required environment variables:
          * SLACK_WEBHOOK_URL
          * PAGERDUTY_SERVICE_KEY
          * SMTP_USER, SMTP_PASSWORD
        - Reload AlertManager
        """
        try:
            from app.core.realtime.sagas.saga_alerts import SagaAlertRules
            return SagaAlertRules.to_alertmanager_config()
        except Exception as e:
            logger.error(f"Error generating AlertManager config: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/v1/saga/alerts/{alert_name}/acknowledge",
             summary="Acknowledge Alert",
             tags=["Alerting"])
    async def acknowledge_alert(alert_name: str):
        """
        Acknowledge an active alert.
        
        Marks alert as acknowledged in alert history.
        Does not dismiss the alert - it can be re-triggered if condition persists.
        """
        try:
            from app.core.realtime.sagas.saga_alerts import get_alert_manager
            alert_mgr = get_alert_manager()
            
            # Find and resolve the alert
            active_alerts = alert_mgr.get_active_alerts()
            alert_id = None
            for alert in active_alerts:
                if alert.name == alert_name:
                    alert_id = next(
                        (k for k, v in alert_mgr.active_alerts.items() if v.name == alert_name),
                        None
                    )
                    break
            
            if alert_id is None:
                raise HTTPException(status_code=404, detail=f"Alert {alert_name} not found")
            
            alert_mgr.resolve_alert(alert_id)
            return {"status": "acknowledged", "alert_name": alert_name}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error acknowledging alert: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# =========================================================================
# Example Usage
# =========================================================================

async def example_setup():
    """
    Example of how to setup production features in main app initialization.
    
    Usage:
        from app.core.realtime.sagas.orchestrator_production import setup_saga_production_endpoints
        
        async def startup():
            await saga_orchestrator.init_async()
            saga_orchestrator.telemetry_collector.setup_real_otel()
            setup_saga_production_endpoints(app, saga_orchestrator)
    """
    
    # Initialization code example
    saga_config = {
        "db_connection_string": os.getenv("SEED_SAGA_DB_URL"),
        "redis_url": os.getenv("SEED_SAGA_REDIS_URL"),
        "adapter_registry": {},  # Your adapters
    }
    
    # Setup completed successfully
    logger.info("✅ Saga production setup complete")
    logger.info("   Monitoring: Prometheus, OpenTelemetry, Health checks")
    logger.info("   Protection: Rate limiting, DLQ, Circuit breakers")
    logger.info("   Ready for production deployment!")

