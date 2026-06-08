"""
Alert Manager integration for Saga production monitoring.
Generates alert rules and threshold definitions for critical metrics.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertState(str, Enum):
    """Alert state."""
    ACTIVE = "active"
    RESOLVED = "resolved"
    INHIBITED = "inhibited"


@dataclass
class AlertRule:
    """Represents an alert rule."""
    name: str
    description: str
    condition: str  # Prometheus query
    duration: str  # e.g., "5m", "10m"
    severity: AlertSeverity
    annotations: Dict[str, str]
    labels: Dict[str, str]


@dataclass
class Alert:
    """Represents an active alert instance."""
    name: str
    severity: AlertSeverity
    state: AlertState
    timestamp: float
    value: float
    message: str
    labels: Dict[str, str]
    
    def to_dict(self) -> dict:
        """Convert alert to dictionary."""
        return {
            "name": self.name,
            "severity": self.severity.value,
            "state": self.state.value,
            "timestamp": self.timestamp,
            "value": self.value,
            "message": self.message,
            "labels": self.labels,
        }


class SagaAlertRules:
    """Manages Saga alert rules and definitions."""
    
    # Critical threshold definitions
    THRESHOLDS = {
        "success_rate_min": 90.0,      # Success rate must be >= 90%
        "failure_rate_max": 10.0,      # Failure rate must be <= 10%
        "compensation_rate_max": 5.0,  # Compensation rate must be <= 5%
        "lock_wait_p99_max": 5000,     # P99 lock wait must be <= 5000ms
        "circuit_breaker_duration_max": 60000,  # Circuit breaker should not be open > 60s
    }
    
    # Alert evaluation window
    ALERT_WINDOW = "5m"  # Evaluate over 5 minute window
    
    @classmethod
    def get_all_rules(cls) -> List[AlertRule]:
        """Get all configured alert rules."""
        return [
            cls._get_success_rate_rule(),
            cls._get_failure_rate_rule(),
            cls._get_compensation_rate_rule(),
            cls._get_lock_contention_rule(),
            cls._get_circuit_breaker_rule(),
            cls._get_dlq_buildup_rule(),
        ]
    
    @classmethod
    def _get_success_rate_rule(cls) -> AlertRule:
        """Success rate alert rule (< 90%)."""
        return AlertRule(
            name="SagaSuccessRateLow",
            description="Saga success rate is below acceptable threshold (90%)",
            condition=f"saga_success_rate_percent < {cls.THRESHOLDS['success_rate_min']}",
            duration="5m",
            severity=AlertSeverity.CRITICAL,
            annotations={
                "summary": "Saga success rate is low: {{ $value }}%",
                "description": "Success rate has been below 90% for 5 minutes. Current value: {{ $value }}%",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#low-success-rate",
            },
            labels={
                "component": "saga",
                "metric_type": "success_rate",
            }
        )
    
    @classmethod
    def _get_failure_rate_rule(cls) -> AlertRule:
        """Failure rate alert rule (> 10%)."""
        return AlertRule(
            name="SagaFailureRateHigh",
            description="Saga failure rate exceeds acceptable threshold (10%)",
            condition=f"saga_failure_rate_percent > {cls.THRESHOLDS['failure_rate_max']}",
            duration="5m",
            severity=AlertSeverity.CRITICAL,
            annotations={
                "summary": "Saga failure rate is high: {{ $value }}%",
                "description": "Failure rate has been above 10% for 5 minutes. Current value: {{ $value }}%",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#high-failure-rate",
            },
            labels={
                "component": "saga",
                "metric_type": "failure_rate",
            }
        )
    
    @classmethod
    def _get_compensation_rate_rule(cls) -> AlertRule:
        """Compensation rate alert rule (> 5%)."""
        return AlertRule(
            name="SagaCompensationRateHigh",
            description="Saga compensation rate exceeds acceptable threshold (5%)",
            condition=f"saga_compensation_rate_percent > {cls.THRESHOLDS['compensation_rate_max']}",
            duration="10m",
            severity=AlertSeverity.WARNING,
            annotations={
                "summary": "High saga compensation rate: {{ $value }}%",
                "description": "Compensation rate has been above 5% for 10 minutes. Current value: {{ $value }}%. "
                              "This indicates that many sagas are failing and being rolled back.",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#high-compensation-rate",
            },
            labels={
                "component": "saga",
                "metric_type": "compensation_rate",
            }
        )
    
    @classmethod
    def _get_lock_contention_rule(cls) -> AlertRule:
        """Lock contention alert rule (P99 > 5000ms)."""
        return AlertRule(
            name="SagaLockContentionHigh",
            description="Lock contention P99 exceeds acceptable threshold (5000ms)",
            condition=f"saga_lock_contention_wait_p99_ms > {cls.THRESHOLDS['lock_wait_p99_max']}",
            duration="5m",
            severity=AlertSeverity.WARNING,
            annotations={
                "summary": "High lock contention detected: P99 = {{ $value }}ms",
                "description": "P99 lock wait time has been above 5000ms for 5 minutes. Current value: {{ $value }}ms. "
                              "This indicates potential bottlenecks in saga state management.",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#lock-contention",
            },
            labels={
                "component": "saga",
                "metric_type": "lock_contention",
            }
        )
    
    @classmethod
    def _get_circuit_breaker_rule(cls) -> AlertRule:
        """Circuit breaker alert rule (open duration > 60s)."""
        return AlertRule(
            name="SagaCircuitBreakerOpen",
            description="Circuit breaker is open for adapter longer than threshold",
            condition="max(saga_circuit_breaker_open) > 0 for 1m",
            duration="1m",
            severity=AlertSeverity.CRITICAL,
            annotations={
                "summary": "Circuit breaker open for {{ $labels.adapter }}",
                "description": "Circuit breaker for adapter '{{ $labels.adapter }}' has been open for over 1 minute. "
                              "This adapter may be experiencing issues.",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#circuit-breaker-open",
            },
            labels={
                "component": "saga",
                "metric_type": "circuit_breaker",
            }
        )
    
    @classmethod
    def _get_dlq_buildup_rule(cls) -> AlertRule:
        """Dead letter queue buildup alert rule."""
        return AlertRule(
            name="SagaDLQBuildup",
            description="Dead letter queue is building up (more than 100 items)",
            condition="dlq_size > 100",
            duration="10m",
            severity=AlertSeverity.WARNING,
            annotations={
                "summary": "Dead letter queue buildup detected: {{ $value }} items",
                "description": "Dead letter queue has more than 100 items for 10 minutes. Current size: {{ $value }} items. "
                              "Failed sagas may not be retried efficiently.",
                "runbook_url": "https://docs.example.com/saga/troubleshooting#dlq-buildup",
            },
            labels={
                "component": "saga",
                "metric_type": "dlq",
            }
        )
    
    @classmethod
    def to_prometheus_rules(cls) -> str:
        """Generate Prometheus alert rules in YAML format."""
        rules = cls.get_all_rules()
        
        yaml_lines = [
            "# Saga Production Alerting Rules",
            "# Auto-generated by SagaAlertRules",
            "groups:",
            "  - name: saga_alerts",
            "    interval: 30s",
            "    rules:",
        ]
        
        for rule in rules:
            yaml_lines.extend(cls._rule_to_yaml(rule))
        
        return "\n".join(yaml_lines)
    
    @classmethod
    def _rule_to_yaml(cls, rule: AlertRule) -> List[str]:
        """Convert alert rule to YAML format."""
        lines = [
            f"      - alert: {rule.name}",
            f"        expr: {rule.condition}",
            f"        for: {rule.duration}",
            "        labels:",
            f"          severity: {rule.severity.value}",
        ]
        
        for key, value in rule.labels.items():
            lines.append(f"          {key}: {value}")
        
        lines.append("        annotations:")
        for key, value in rule.annotations.items():
            # Escape quotes in annotation values
            escaped_value = value.replace('"', '\\"')
            lines.append(f'          {key}: "{escaped_value}"')
        
        lines.append("")
        return lines
    
    @classmethod
    def to_alertmanager_config(cls) -> dict:
        """Generate AlertManager configuration."""
        return {
            "global": {
                "resolve_timeout": "5m",
            },
            "route": {
                "receiver": "saga_alerts",
                "group_by": ["alertname", "severity"],
                "group_wait": "10s",
                "group_interval": "10s",
                "repeat_interval": "1h",
                "routes": [
                    {
                        "match": {"severity": "critical"},
                        "receiver": "saga_critical",
                        "continue": True,
                        "repeat_interval": "15m",
                    },
                    {
                        "match": {"severity": "warning"},
                        "receiver": "saga_warnings",
                        "repeat_interval": "30m",
                    },
                ]
            },
            "receivers": [
                {
                    "name": "saga_alerts",
                    "slack_configs": [
                        {
                            "api_url": "${SLACK_WEBHOOK_URL}",
                            "channel": "#saga-alerts",
                            "title": "[{{ .GroupLabels.severity }}] {{ .GroupLabels.alertname }}",
                            "text": "{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}",
                        }
                    ],
                    "email_configs": [
                        {
                            "to": "saga-team@example.com",
                            "from": "alertmanager@example.com",
                            "smarthost": "smtp.example.com:587",
                            "auth_username": "${SMTP_USER}",
                            "auth_password": "${SMTP_PASSWORD}",
                            "headers": {
                                "Subject": "[{{ .GroupLabels.severity }}] Saga Alert: {{ .GroupLabels.alertname }}",
                            },
                        }
                    ],
                },
                {
                    "name": "saga_critical",
                    "pagerduty_configs": [
                        {
                            "service_key": "${PAGERDUTY_SERVICE_KEY}",
                            "description": "{{ .GroupLabels.alertname }}: {{ (index .Alerts 0).Annotations.summary }}",
                        }
                    ],
                },
                {
                    "name": "saga_warnings",
                    "slack_configs": [
                        {
                            "api_url": "${SLACK_WEBHOOK_URL}",
                            "channel": "#saga-warnings",
                            "title": "[WARNING] {{ .GroupLabels.alertname }}",
                            "text": "{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}",
                        }
                    ],
                },
            ],
            "inhibit_rules": [
                {
                    "source_match": {"severity": "critical"},
                    "target_match": {"severity": "warning"},
                    "equal": ["alertname"],
                },
            ],
        }
    
    @classmethod
    def get_alert_thresholds(cls) -> Dict[str, Dict[str, Any]]:
        """Get alert threshold definitions."""
        return {
            "success_rate": {
                "threshold": cls.THRESHOLDS["success_rate_min"],
                "operator": ">=",
                "unit": "%",
                "description": "Saga success rate must be at least 90%",
                "severity": "CRITICAL",
            },
            "failure_rate": {
                "threshold": cls.THRESHOLDS["failure_rate_max"],
                "operator": "<=",
                "unit": "%",
                "description": "Saga failure rate must not exceed 10%",
                "severity": "CRITICAL",
            },
            "compensation_rate": {
                "threshold": cls.THRESHOLDS["compensation_rate_max"],
                "operator": "<=",
                "unit": "%",
                "description": "Compensation rate must not exceed 5%",
                "severity": "WARNING",
            },
            "lock_contention_p99": {
                "threshold": cls.THRESHOLDS["lock_wait_p99_max"],
                "operator": "<=",
                "unit": "ms",
                "description": "P99 lock wait time must not exceed 5000ms",
                "severity": "WARNING",
            },
            "circuit_breaker_duration": {
                "threshold": cls.THRESHOLDS["circuit_breaker_duration_max"],
                "operator": "<=",
                "unit": "ms",
                "description": "Circuit breaker should not be open for more than 60 seconds",
                "severity": "CRITICAL",
            },
        }


class AlertManager:
    """Manages alert instances and state."""
    
    def __init__(self):
        """Initialize alert manager."""
        self.active_alerts: Dict[str, Alert] = {}
        self.resolved_alerts: List[Alert] = []
        self.alert_history: List[Alert] = []
    
    def create_alert(
        self,
        name: str,
        severity: AlertSeverity,
        value: float,
        message: str,
        labels: Optional[Dict[str, str]] = None,
    ) -> Alert:
        """Create and register an alert."""
        import time
        
        alert = Alert(
            name=name,
            severity=severity,
            state=AlertState.ACTIVE,
            timestamp=time.time(),
            value=value,
            message=message,
            labels=labels or {},
        )
        
        alert_id = f"{name}:{','.join(f'{k}={v}' for k, v in (labels or {}).items())}"
        self.active_alerts[alert_id] = alert
        self.alert_history.append(alert)
        
        logger.warning(f"Alert created: {name} (severity={severity.value}, value={value})")
        return alert
    
    def resolve_alert(self, alert_id: str) -> Optional[Alert]:
        """Resolve an active alert."""
        if alert_id not in self.active_alerts:
            return None
        
        alert = self.active_alerts.pop(alert_id)
        alert.state = AlertState.RESOLVED
        self.resolved_alerts.append(alert)
        
        logger.info(f"Alert resolved: {alert.name}")
        return alert
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts."""
        return list(self.active_alerts.values())
    
    def get_alert_summary(self) -> dict:
        """Get summary of current alert state."""
        active = self.get_active_alerts()
        critical = [a for a in active if a.severity == AlertSeverity.CRITICAL]
        warnings = [a for a in active if a.severity == AlertSeverity.WARNING]
        
        return {
            "total_active": len(active),
            "critical": len(critical),
            "warnings": len(warnings),
            "active_alerts": [a.to_dict() for a in active],
            "recent_history": [a.to_dict() for a in self.alert_history[-10:]],
        }


# Global alert manager instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Get or create global alert manager instance."""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
