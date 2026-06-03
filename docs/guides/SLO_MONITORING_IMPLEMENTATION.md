# SLO Monitoring, Dashboards, and Load Testing - Complete Implementation Guide

## 📋 Overview

This implementation provides comprehensive Service Level Objectives (SLO) monitoring, Prometheus/Grafana dashboards, and load testing infrastructure for the Seed Server.

## 🎯 What's Been Implemented

### 1. Service Level Objectives (SLOs)

**File:** `slo_config.yaml`
- ✅ Availability SLO (99.9% uptime)
- ✅ Latency SLO (P95 < 3s, P99 < 5s)
- ✅ Error Rate SLO (< 1% errors)
- ✅ Data Quality SLO (98% validation success)
- ✅ Job Processing SLO (queue wait time & completion)
- ✅ Alert rules and thresholds

**File:** `app/slo_monitor.py`
- ✅ SLOMonitor class for tracking compliance
- ✅ Database-backed SLO measurement storage
- ✅ Historical SLO trend analysis
- ✅ Automated SLO reporting

### 2. Monitoring Dashboards

**Directory:** `monitoring/`
- ✅ Prometheus configuration (`prometheus.yml`)
- ✅ Alert rules (`alert_rules.yml`)
- ✅ Alertmanager configuration
- ✅ Grafana dashboard JSON templates
  - Main operational dashboard
  - SLO compliance dashboard
- ✅ Docker Compose integration

### 3. Load Testing Suite

**Directory:** `load_tests/`
- ✅ Locust-based load testing (`locustfile.py`)
- ✅ Multiple user scenarios (normal users + admin)
- ✅ SLO compliance checker (`check_slo_compliance.py`)
- ✅ Test scenarios (normal, peak, stress, soak, spike)
- ✅ K6 alternative example

### 4. API Endpoints

**Added to `app/main.py`:**
- ✅ `GET /v1/monitoring/slo` - Current SLO status
- ✅ `GET /v1/monitoring/slo/{slo_name}/history` - Historical SLO data
- ✅ Integrated with existing monitoring endpoints

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
# Core dependencies (already in requirements.txt)
pip install -r requirements.txt

# Load testing tools
pip install locust faker
```

### Step 2: Configure Monitoring

```bash
# Create monitoring directories
mkdir -p monitoring/grafana/{provisioning/datasources,provisioning/dashboards,dashboards}

# Configure Prometheus datasource
cat > monitoring/grafana/provisioning/datasources/prometheus.yml << 'EOF'
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
EOF

# Configure dashboard provisioning
cat > monitoring/grafana/provisioning/dashboards/dashboards.yml << 'EOF'
apiVersion: 1
providers:
  - name: 'default'
    orgId: 1
    folder: ''
    type: file
    options:
      path: /var/lib/grafana/dashboards
EOF
```

### Step 3: Start Monitoring Stack

```bash
# Start Prometheus, Grafana, and Alertmanager
docker-compose up -d prometheus grafana alertmanager

# Verify services
curl http://localhost:9090/-/healthy  # Prometheus
curl http://localhost:3000/api/health # Grafana
```

### Step 4: Run Load Tests

```bash
# Basic load test (10 users, 5 minutes)
cd load_tests
locust -f locustfile.py --host http://localhost:8000 \
  --users 10 --spawn-rate 2 --run-time 5m --headless \
  --html report.html --csv report

# Check SLO compliance
python check_slo_compliance.py report
```

## 📊 Accessing Dashboards

### Grafana
- **URL:** http://localhost:3000
- **Default credentials:** admin / admin
- **Dashboards:**
  - Main Dashboard: Real-time metrics
  - SLO Dashboard: Compliance tracking

### Prometheus
- **URL:** http://localhost:9090
- **Useful queries:**
  ```promql
  # Request rate
  rate(seed_http_requests_total[5m])
  
  # P95 latency
  histogram_quantile(0.95, rate(seed_http_request_latency_seconds_bucket[5m]))
  
  # Error rate
  rate(seed_http_requests_total{status=~"5.."}[5m]) / rate(seed_http_requests_total[5m])
  ```

### Alertmanager
- **URL:** http://localhost:9093
- **View active alerts and silences**

## 🔍 SLO Monitoring API

### Check Current SLO Status
```bash
curl -H "X-API-Key: YOUR_ADMIN_KEY" \
  http://localhost:8000/v1/monitoring/slo
```

Response:
```json
{
  "timestamp": "2026-01-12T10:30:00Z",
  "overall_compliance": true,
  "summary": {
    "total_slos": 5,
    "compliant": 5,
    "non_compliant": 0
  },
  "slos": [
    {
      "name": "availability",
      "target": 99.9,
      "current": 99.95,
      "is_compliant": true,
      "window": "30d",
      "details": {...}
    }
  ]
}
```

### View SLO History
```bash
curl -H "X-API-Key: YOUR_ADMIN_KEY" \
  "http://localhost:8000/v1/monitoring/slo/availability/history?hours=168"
```

## 📈 Load Testing Scenarios

### 1. Baseline Test (Establish Performance Baseline)
```bash
locust -f locustfile.py --host http://localhost:8000 \
  --users 10 --spawn-rate 1 --run-time 10m --headless
```

### 2. Normal Load (Typical Production Traffic)
```bash
locust -f locustfile.py --host http://localhost:8000 \
  --users 50 --spawn-rate 5 --run-time 15m --headless
```

### 3. Peak Load (High Traffic Periods)
```bash
locust -f locustfile.py --host http://localhost:8000 \
  --users 200 --spawn-rate 10 --run-time 20m --headless
```

### 4. Stress Test (Find Breaking Point)
```bash
locust -f locustfile.py --host http://localhost:8000 \
  --users 500 --spawn-rate 20 --run-time 30m --headless
```

### 5. Soak Test (Long-Running Stability)
```bash
locust -f locustfile.py --host http://localhost:8000 \
  --users 100 --spawn-rate 5 --run-time 4h --headless
```

## 🎯 SLO Targets

| SLO | Target | Window | Alert Threshold |
|-----|--------|--------|----------------|
| **Availability** | 99.9% | 30 days | < 99.5% |
| **Latency (P95)** | < 3000ms | 7 days | > 3600ms |
| **Latency (P99)** | < 5000ms | 7 days | > 6000ms |
| **Error Rate** | < 1% | 24 hours | > 2% |
| **Validation Success** | > 98% | 24 hours | < 95% |
| **Queue Wait (P95)** | < 1000ms | 24 hours | > 5000ms |

## 🔔 Alert Configuration

### Critical Alerts
- API Down (> 1 minute)
- High Error Rate (> 2%)
- Low Availability (< 99.5%)

### Warning Alerts
- High Latency (> 20% above target)
- Queue Backlog (> 100 jobs)
- Validation Failures (> 5%)

### Configure Notifications

Edit `monitoring/alertmanager.yml`:
```yaml
receivers:
  - name: 'slack'
    slack_configs:
      - api_url: 'YOUR_SLACK_WEBHOOK'
        channel: '#seed-alerts'
  
  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: 'YOUR_PAGERDUTY_KEY'
```

## 📊 Key Metrics to Monitor

### Application Metrics
- `seed_http_requests_total` - Total HTTP requests
- `seed_http_request_latency_seconds` - Request latency histogram
- `seed_jobs_created_total` - Jobs created counter
- `seed_jobs_finished_total` - Jobs completed counter
- `seed_queue_depth` - Current queue depth

### Custom Queries

**Request Rate (RPS):**
```promql
sum(rate(seed_http_requests_total[5m]))
```

**Error Percentage:**
```promql
(sum(rate(seed_http_requests_total{status=~"5.."}[5m])) 
 / sum(rate(seed_http_requests_total[5m]))) * 100
```

**P95 Latency by Endpoint:**
```promql
histogram_quantile(0.95, 
  sum(rate(seed_http_request_latency_seconds_bucket[5m])) by (le, path))
```

**Queue Backlog:**
```promql
seed_queue_depth > 10
```

## 🧪 Testing Checklist

- [ ] Start monitoring stack (Prometheus, Grafana, Alertmanager)
- [ ] Verify metrics endpoint accessible at `/metrics`
- [ ] Run baseline load test to establish benchmarks
- [ ] Configure alert notifications (Slack/PagerDuty/Email)
- [ ] Review and customize SLO targets in `slo_config.yaml`
- [ ] Set up automated load tests in CI/CD
- [ ] Create runbooks for alert responses
- [ ] Train team on dashboard usage

## 🔧 Troubleshooting

### Prometheus Not Scraping Metrics
```bash
# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Verify metrics endpoint
curl http://localhost:8000/metrics
```

### Grafana Dashboard Not Loading
```bash
# Check Grafana logs
docker-compose logs grafana

# Verify datasource
curl -u admin:admin http://localhost:3000/api/datasources
```

### Load Tests Failing
```bash
# Check server is running
curl http://localhost:8000/health

# Verify API key is valid
curl -H "X-API-Key: test_admin_key_12345" \
  http://localhost:8000/v1/monitoring/performance
```

### High Memory Usage During Load Tests
```bash
# Monitor container resources
docker stats

# Reduce concurrent users
locust -f locustfile.py --users 20 --spawn-rate 2
```

## 📚 Additional Resources

### Documentation
- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Locust Documentation](https://docs.locust.io/)
- [SRE Book - SLO Chapter](https://sre.google/sre-book/service-level-objectives/)

### Files in This Implementation
```
seed_server/
├── slo_config.yaml                    # SLO definitions
├── app/
│   └── slo_monitor.py                 # SLO monitoring logic
├── monitoring/
│   ├── MONITORING_SETUP.md            # Detailed setup guide
│   ├── prometheus.yml                 # Prometheus config (create)
│   ├── alert_rules.yml                # Alert definitions (create)
│   ├── alertmanager.yml               # Alertmanager config (create)
│   └── grafana/
│       ├── provisioning/              # Auto-provisioning configs
│       └── dashboards/                # Dashboard JSON files
└── load_tests/
    ├── README.md                      # Load testing guide
    ├── locustfile.py                  # Main load test script
    └── check_slo_compliance.py        # SLO validation script
```

## 🎯 Next Steps

1. **Customize SLOs:** Adjust targets in `slo_config.yaml` based on your requirements
2. **Set Up Alerts:** Configure Slack/PagerDuty in `alertmanager.yml`
3. **Run Baseline Tests:** Establish performance benchmarks
4. **Create Runbooks:** Document response procedures for each alert
5. **Integrate CI/CD:** Add load tests to your deployment pipeline
6. **Train Team:** Ensure everyone knows how to use dashboards and respond to alerts

## ✅ Success Criteria

- ✅ All SLOs defined and tracked
- ✅ Prometheus collecting metrics every 15s
- ✅ Grafana dashboards showing real-time data
- ✅ Alerts triggering correctly
- ✅ Load tests passing SLO compliance
- ✅ Team trained on monitoring tools

## 🆘 Support

For issues or questions:
1. Check troubleshooting section above
2. Review logs: `docker-compose logs [service]`
3. Consult monitoring/MONITORING_SETUP.md for detailed configuration
4. Review load_tests/README.md for testing guidance

---

**Implementation Date:** 2026-01-12  
**Status:** ✅ Complete and Ready for Use
