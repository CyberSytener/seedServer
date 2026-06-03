# Quick Reference: SLO Monitoring & Load Testing

## 🚀 Quick Start Commands

### Start Monitoring
```bash
# Start Prometheus + Grafana
docker-compose up -d prometheus grafana alertmanager

# Access dashboards
# Grafana: http://localhost:3000 (admin/admin)
# Prometheus: http://localhost:9090
# Alertmanager: http://localhost:9093
```

### Check SLO Status
```bash
# Get current SLO compliance
curl -H "X-API-Key: YOUR_ADMIN_KEY" http://localhost:8000/v1/monitoring/slo | jq

# View SLO history
curl -H "X-API-Key: YOUR_ADMIN_KEY" \
  "http://localhost:8000/v1/monitoring/slo/availability/history?hours=24" | jq
```

### Run Load Tests
```bash
# Install dependencies
pip install locust faker

# Quick test (10 users, 5 min)
cd load_tests
locust -f locustfile.py --host http://localhost:8000 \
  --users 10 --spawn-rate 2 --run-time 5m --headless

# Check compliance
python check_slo_compliance.py report
```

## 📊 Key Files

| File | Purpose |
|------|---------|
| `slo_config.yaml` | SLO definitions and targets |
| `app/slo_monitor.py` | SLO monitoring implementation |
| `monitoring/prometheus.yml` | Prometheus configuration |
| `monitoring/alert_rules.yml` | Alert definitions |
| `load_tests/locustfile.py` | Load testing scenarios |

## 🎯 SLO Targets

- **Availability:** 99.9% uptime
- **Latency P95:** < 3 seconds
- **Error Rate:** < 1%
- **Validation Success:** > 98%

## 📈 Key Metrics

```promql
# Request rate
rate(seed_http_requests_total[5m])

# P95 latency
histogram_quantile(0.95, rate(seed_http_request_latency_seconds_bucket[5m]))

# Error rate
rate(seed_http_requests_total{status=~"5.."}[5m]) / rate(seed_http_requests_total[5m])
```

## 🔔 Common Alerts

- **Critical:** API Down, High Error Rate
- **Warning:** High Latency, Queue Backlog

## 📚 Documentation

- Full guide: `SLO_MONITORING_IMPLEMENTATION.md`
- Monitoring setup: `monitoring/MONITORING_SETUP.md`
- Load testing: `load_tests/README.md`
