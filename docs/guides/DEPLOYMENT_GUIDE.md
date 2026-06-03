# Deployment Guide: Learning Path System

## рџљЂ Quick Start

### Prerequisites

- Python 3.10+
- Redis 7+
- Gemini API Key

### Local Development Setup

```powershell
# 1. Clone and navigate to project
cd c:\Users\Exempel\Desktop\seed.server.v5\seed_server

# 2. Set environment variables
$env:GEMINI_API_KEY="your-gemini-api-key-here"
$env:REDIS_URL="redis://localhost:6379/0"

# 3. Start Redis (Option A: Docker)
docker run -d -p 6379:6379 --name seed_redis redis:7-alpine

# 3. Start Redis (Option B: Docker Compose)
docker-compose -f docker-compose-full.yml up redis -d

# 4. Start API Server
python run.py

# 5. Start Worker (in separate terminal)
python run_worker.py --queue q_fast --concurrency 3

# 6. Verify everything is running
python test_end_to_end_flow.py
```

---

## рџђі Docker Deployment

### Full Stack with Docker Compose

```powershell
# Build and start all services
docker-compose -f docker-compose-full.yml up --build -d

# Check status
docker-compose -f docker-compose-full.yml ps

# View logs
docker-compose -f docker-compose-full.yml logs -f

# Stop all services
docker-compose -f docker-compose-full.yml down
```

**Services:**
- `redis` - Job queue (port 6379)
- `api` - FastAPI server (port 8000)
- `worker` - Background job processor

---

## рџ“Љ Monitoring

### Health Checks

```powershell
# API health
curl http://localhost:8000/health

# Redis health
docker exec seed_redis redis-cli ping

# Worker status (check logs)
docker logs seed_worker --tail 50
```

### Performance Metrics

```powershell
# Check Redis queue depth
docker exec seed_redis redis-cli LLEN q_fast

# Check active connections
docker stats seed_api seed_worker

# Database size
ls -lh data/seed_v5.db
```

---

## рџ”§ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Gemini API key (required) | None |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` |
| `DATABASE_PATH` | SQLite database path | `./data/seed_v5.db` |
| `API_HOST` | API bind host | `0.0.0.0` |
| `API_PORT` | API bind port | `8000` |
| `WORKER_CONCURRENCY` | Jobs processed simultaneously | `3` |
| `WORKER_QUEUE` | Queue name to consume | `q_fast` |

### Queue Configuration

**Available Queues:**
- `q_fast` - High priority (interactive requests)
- `q_batch` - Normal priority (bulk operations)
- `q_low` - Low priority (background tasks)

**Running Multiple Workers:**
```powershell
# Terminal 1: Fast queue (3 workers)
python run_worker.py --queue q_fast --concurrency 3

# Terminal 2: Batch queue (2 workers)
python run_worker.py --queue q_batch --concurrency 2

# Terminal 3: Low priority (1 worker)
python run_worker.py --queue q_low --concurrency 1
```

---

## рџ§Є Testing

### Unit Tests

```powershell
# All tests
pytest -v

# Specific modules
pytest test_path_models.py -v
pytest test_path_analytics.py -v

# With coverage
pytest --cov=app --cov-report=html
```

### Integration Tests

```powershell
# End-to-end flow test
python test_end_to_end_flow.py

# Requires:
# - Redis running
# - API server running
# - Worker running
# - GEMINI_API_KEY set
```

### Load Testing

```powershell
# Install locust
pip install locust

# Run load test (if you have locustfile.py)
locust -f locustfile.py --host http://localhost:8000
```

---

## рџ“€ Scaling Strategies

### Small Scale (< 100 users)

**Architecture:**
- Single server (API + Worker)
- Local Redis
- SQLite database

**Resources:**
- 2 CPU cores
- 4 GB RAM
- 10 GB disk

**Configuration:**
```yaml
api: 1 instance
worker: 1 instance (3 concurrent jobs)
redis: 256 MB max memory
```

### Medium Scale (100-1000 users)

**Architecture:**
- Separate API and Worker containers
- Redis cluster or managed service
- Consider PostgreSQL migration

**Resources:**
- API: 4 CPU cores, 8 GB RAM
- Worker: 2 CPU cores per instance, 4 GB RAM
- Redis: 2 GB memory

**Configuration:**
```yaml
api: 2-3 instances (load balanced)
worker: 3-5 instances (5 concurrent jobs each)
redis: 2 GB max memory, persistence enabled
```

### Large Scale (> 1000 users)

**Architecture:**
- Kubernetes deployment
- Redis Cluster (3+ nodes)
- PostgreSQL with read replicas
- CDN for static content

**Resources:**
- API: Auto-scale 5-20 pods (4 cores, 8 GB each)
- Worker: Auto-scale 5-15 pods (2 cores, 4 GB each)
- Redis: 3-node cluster (4 GB each)
- PostgreSQL: Primary + 2 replicas (8 cores, 16 GB)

**Configuration:**
```yaml
api:
  replicas: 5-20 (HPA based on CPU/requests)
  resources:
    requests: { cpu: 2, memory: 4Gi }
    limits: { cpu: 4, memory: 8Gi }

worker:
  replicas: 5-15 (HPA based on queue depth)
  resources:
    requests: { cpu: 1, memory: 2Gi }
    limits: { cpu: 2, memory: 4Gi }

redis:
  cluster: 3 nodes
  memory: 4Gi per node
  persistence: enabled

database:
  engine: PostgreSQL 15
  primary: 8 cores, 16 GB
  replicas: 2 (read-only)
```

---

## рџ”ђ Security Checklist

- [ ] Use strong API keys (32+ characters)
- [ ] Enable HTTPS/TLS in production
- [ ] Restrict Redis to localhost or VPC
- [ ] Use environment variables for secrets
- [ ] Enable CORS only for trusted origins
- [ ] Rate limit API endpoints
- [ ] Monitor for suspicious activity
- [ ] Regular security updates
- [ ] Backup database regularly
- [ ] Use read-only volumes for code

---

## рџђ› Troubleshooting

### API won't start

**Symptoms:** `python run.py` exits immediately

**Solutions:**
```powershell
# Check imports
python -c "from app.main import app; print('вњ… OK')"

# Check logs
python run.py 2>&1 | Out-File -FilePath startup.log

# Check port availability
netstat -ano | findstr :8000
```

### Worker not processing jobs

**Symptoms:** Jobs stuck in "pending" status

**Solutions:**
```powershell
# Check Redis connection
docker exec seed_redis redis-cli ping

# Check queue depth
docker exec seed_redis redis-cli LLEN q_fast

# Check worker logs
docker logs seed_worker --tail 50

# Manually inspect job
docker exec seed_redis redis-cli LINDEX q_fast 0
```

### Slow LLM generation

**Symptoms:** Jobs take > 60 seconds

**Solutions:**
```powershell
# Check Gemini API key
echo $env:GEMINI_API_KEY

# Test direct API call
python -c "from app.infrastructure.llm.client import get_llm_client; import asyncio; asyncio.run(test())"

# Check network latency
ping generativelanguage.googleapis.com

# Increase timeout
# In run_worker.py, modify timeout_sec in LLM client
```

### Memory issues

**Symptoms:** OOMKilled, slow performance

**Solutions:**
```powershell
# Check memory usage
docker stats

# Reduce connection pool size (llm_client_async.py)
max_connections=50  # Down from 100

# Reduce worker concurrency
python run_worker.py --concurrency 1

# Limit Redis memory
docker exec seed_redis redis-cli CONFIG SET maxmemory 128mb
```

---

## рџ“ќ Maintenance Tasks

### Daily

- [ ] Check API health endpoint
- [ ] Monitor error logs
- [ ] Check Redis memory usage
- [ ] Verify worker is processing jobs

### Weekly

- [ ] Review performance metrics
- [ ] Check database size
- [ ] Analyze failed jobs
- [ ] Update dependencies (if needed)

### Monthly

- [ ] Backup database
- [ ] Review security logs
- [ ] Optimize database (VACUUM)
- [ ] Update documentation

---

## рџ”„ Backup & Recovery

### Database Backup

```powershell
# Backup SQLite
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item data/seed_v5.db "backups/seed_v5_$timestamp.db"

# Compress
Compress-Archive -Path "backups/seed_v5_$timestamp.db" -DestinationPath "backups/seed_v5_$timestamp.zip"

# Restore
Copy-Item "backups/seed_v5_20260112_143000.db" data/seed_v5.db
```

### Redis Backup

```powershell
# Save snapshot
docker exec seed_redis redis-cli SAVE

# Copy snapshot
docker cp seed_redis:/data/dump.rdb ./backups/redis_dump.rdb

# Restore
docker cp ./backups/redis_dump.rdb seed_redis:/data/dump.rdb
docker restart seed_redis
```

---

## рџ“Љ Production Metrics

### Key Performance Indicators

| Metric | Target | Critical |
|--------|--------|----------|
| API Response Time (p95) | < 100ms | > 500ms |
| Blueprint Generation | < 5s | > 10s |
| Content Generation | < 30s | > 60s |
| Job Queue Depth | < 10 | > 100 |
| Error Rate | < 1% | > 5% |
| API Availability | > 99.5% | < 99% |

### Alerting Rules

```yaml
# Example Prometheus alerts
groups:
  - name: learning_path
    rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.05
        for: 5m
        
      - alert: SlowGeneration
        expr: histogram_quantile(0.95, llm_generation_seconds_bucket) > 60
        for: 10m
        
      - alert: QueueBacklog
        expr: queue_depth{queue="q_fast"} > 100
        for: 5m
```

---

## рџљ¦ Deployment Checklist

### Pre-Deployment

- [ ] All tests passing
- [ ] Environment variables configured
- [ ] Redis accessible
- [ ] Database migrations applied
- [ ] SSL/TLS certificates ready
- [ ] Backup strategy in place

### Deployment

- [ ] Build Docker images
- [ ] Push to registry
- [ ] Update deployment config
- [ ] Apply Kubernetes manifests
- [ ] Verify health checks
- [ ] Run smoke tests

### Post-Deployment

- [ ] Monitor error logs
- [ ] Check performance metrics
- [ ] Verify worker processing
- [ ] Test critical flows
- [ ] Update documentation
- [ ] Notify team

---

## рџ“љ Additional Resources

- [LEARNING_PATH_API.md](LEARNING_PATH_API.md) - API documentation
- [LEARNING_PATH_ANALYTICS.md](LEARNING_PATH_ANALYTICS.md) - Analytics guide
- [SCALABILITY_UX_IMPROVEMENTS.md](SCALABILITY_UX_IMPROVEMENTS.md) - Architecture details
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Redis Docs](https://redis.io/docs/)

---

## рџ† Support

**Issues?** Check:
1. This deployment guide
2. API documentation
3. GitHub issues
4. Contact platform team

**Performance problems?** Run:
```powershell
python test_end_to_end_flow.py
```

This will validate all components and identify bottlenecks.

