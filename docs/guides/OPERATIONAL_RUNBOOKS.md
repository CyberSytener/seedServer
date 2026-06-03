# Operational Runbooks

## Overview
This document provides operational procedures, troubleshooting guides, and emergency response protocols for the Seed Server in production environments.

## Table of Contents
1. [Service Management](#service-management)
2. [Database Operations](#database-operations)
3. [Monitoring & Alerts](#monitoring--alerts)
4. [Incident Response](#incident-response)
5. [Troubleshooting](#troubleshooting)
6. [Backup & Recovery](#backup--recovery)
7. [Performance Tuning](#performance-tuning)

---

## Service Management

### Starting the Server

**Development:**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Production:**
```bash
# Using systemd
sudo systemctl start seed-server

# Using Docker
docker-compose up -d

# Direct command
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Stopping the Server

**Graceful shutdown:**
```bash
sudo systemctl stop seed-server
# or
docker-compose down
# or
kill -SIGTERM $(cat api_server.pid)
```

**Force stop:**
```bash
sudo systemctl kill seed-server
# or
docker-compose kill
# or
kill -SIGKILL $(cat api_server.pid)
```

### Restarting the Server

```bash
# Graceful restart
sudo systemctl restart seed-server

# Reload configuration without downtime
sudo systemctl reload seed-server

# Docker
docker-compose restart
```

### Health Checks

**Endpoint checks:**
```bash
# Basic health
curl http://localhost:8000/health

# Detailed metrics
curl http://localhost:8000/metrics

# Redis connectivity
curl http://localhost:8000/health/redis

# Database connectivity
curl http://localhost:8000/health/db
```

**Expected responses:**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-01-12T14:30:00Z",
  "components": {
    "database": "ok",
    "redis": "ok",
    "llm_providers": {
      "gemini": "ok",
      "openai": "ok"
    }
  }
}
```

---

## Database Operations

### Backup Database

**Automated backup:**
```bash
# Linux/Mac
./scripts/backup_database.sh

# Windows
.\scripts\backup_database.ps1
```

**Manual backup:**
```bash
sqlite3 data/seed_server.db ".backup 'data/backups/manual_$(date +%Y%m%d_%H%M%S).db'"
```

**Verify backup:**
```bash
sqlite3 data/backups/seed_server_20260112_143000.db "PRAGMA integrity_check;"
```

### Restore Database

**From backup:**
```bash
# 1. Stop server
sudo systemctl stop seed-server

# 2. Backup current database (safety)
cp data/seed_server.db data/seed_server.db.before_restore

# 3. Restore from backup
gunzip -c data/backups/seed_server_20260112_143000.db.gz > data/seed_server.db

# 4. Verify integrity
sqlite3 data/seed_server.db "PRAGMA integrity_check;"

# 5. Start server
sudo systemctl start seed-server
```

### Run Migrations

**Apply pending migrations:**
```bash
# Check current version
alembic current

# Show pending migrations
alembic history --verbose

# Backup before migration
./scripts/backup_database.sh

# Apply migrations
alembic upgrade head

# Verify
alembic current
```

### Database Maintenance

**Vacuum database (reclaim space):**
```bash
sqlite3 data/seed_server.db "VACUUM;"
```

**Analyze query planner:**
```bash
sqlite3 data/seed_server.db "ANALYZE;"
```

**Check database size:**
```bash
du -h data/seed_server.db
```

---

## Monitoring & Alerts

### Prometheus Metrics

**Access metrics:**
```bash
curl http://localhost:8000/metrics | grep -E "^(http_|job_|queue_)"
```

**Key metrics to monitor:**
- `http_requests_total` - Total HTTP requests
- `http_request_duration_seconds` - Request latency
- `job_queue_size` - Queue depth
- `job_execution_duration_seconds` - Job processing time
- `llm_api_calls_total` - LLM API usage
- `redis_connection_errors` - Redis connectivity issues

### Alert Thresholds

**Critical alerts:**
- HTTP 5xx rate > 5% for 5 minutes
- Request latency p95 > 2 seconds
- Queue depth > 1000 jobs
- Redis connection failures
- Database errors

**Warning alerts:**
- HTTP 4xx rate > 10%
- Request latency p95 > 1 second
- Queue depth > 500 jobs
- Memory usage > 80%
- Disk usage > 85%

### Log Monitoring

**View logs:**
```bash
# Real-time logs
tail -f logs/server.log

# Last 100 errors
grep ERROR logs/server.log | tail -100

# Search for specific user
grep "user_id=123" logs/server.log
```

**Log levels:**
- `CRITICAL` - System-level failures
- `ERROR` - Request failures, exceptions
- `WARNING` - Degraded performance, retries
- `INFO` - Normal operations
- `DEBUG` - Detailed debugging (disable in prod)

### Grafana Dashboards

**Key dashboards:**
1. **Overview Dashboard**: Request rate, latency, error rate
2. **Job Queue Dashboard**: Queue depths, processing times
3. **LLM Dashboard**: API calls, tokens, costs
4. **Resource Dashboard**: CPU, memory, disk, network

---

## Incident Response

### High Error Rate

**Symptoms:**
- 5xx errors increasing
- Users reporting failures
- Alertmanager firing

**Immediate actions:**
1. Check server health: `curl http://localhost:8000/health`
2. Check logs: `tail -100 logs/server.log | grep ERROR`
3. Check dependencies: Redis, database connectivity
4. Check resource usage: `top`, `df -h`

**Common causes:**
- Database locked (SQLite write contention)
- Redis connection pool exhausted
- LLM API rate limits
- Out of memory/disk space

**Mitigation:**
```bash
# Restart server
sudo systemctl restart seed-server

# Clear Redis cache if corrupted
redis-cli FLUSHDB

# Check database locks
sqlite3 data/seed_server.db "PRAGMA lock_status;"

# Scale workers if needed
# Edit docker-compose.yml, increase replicas
```

### High Latency

**Symptoms:**
- p95 latency > 2 seconds
- Slow response times
- Queue backlog building

**Debugging:**
```bash
# Check queue sizes
redis-cli LLEN q_fast
redis-cli LLEN q_batch
redis-cli LLEN q_low

# Check active jobs
curl http://localhost:8000/jobs/active

# Profile slow requests
# Enable DEBUG logging temporarily
```

**Solutions:**
- Scale workers: Increase worker count in docker-compose
- Optimize database queries: Add indexes, use caching
- Increase rate limits: Adjust LLM provider limits
- Enable Redis persistence: Configure RDB/AOF

### Job Queue Backlog

**Symptoms:**
- Queue depth > 1000
- Jobs timing out
- Users reporting delays

**Actions:**
```bash
# Check queue depths
redis-cli LLEN q_fast  # Should be < 100
redis-cli LLEN q_batch # Should be < 500
redis-cli LLEN q_low   # Can be higher

# Check worker status
curl http://localhost:8000/jobs/workers

# Scale workers
docker-compose up -d --scale worker=4

# Purge failed jobs (careful!)
redis-cli DEL q_failed
```

### Out of Disk Space

**Symptoms:**
- Database write errors
- Log rotation failing
- Backup failures

**Recovery:**
```bash
# Check disk usage
df -h

# Clear old logs
find logs/ -name "*.log.*" -mtime +30 -delete

# Clear old backups
find data/backups/ -name "*.db.gz" -mtime +90 -delete

# Vacuum database
sqlite3 data/seed_server.db "VACUUM;"

# Clear test data (if safe)
rm -rf data/test/*
```

### Redis Connection Issues

**Symptoms:**
- Redis connection errors in logs
- Queue operations failing
- Rate limiting not working

**Debugging:**
```bash
# Check Redis status
redis-cli ping  # Should return PONG

# Check Redis info
redis-cli info

# Check connection count
redis-cli client list | wc -l

# Check memory usage
redis-cli info memory
```

**Solutions:**
```bash
# Restart Redis
sudo systemctl restart redis

# Flush corrupted data (careful!)
redis-cli FLUSHALL

# Increase max connections
# Edit redis.conf: maxclients 10000

# Check network connectivity
telnet localhost 6379
```

---

## Troubleshooting

### Diagnostic Checklist

**When issues occur, check in order:**
1. ✅ Server is running: `systemctl status seed-server`
2. ✅ Health endpoint responding: `curl http://localhost:8000/health`
3. ✅ Redis is accessible: `redis-cli ping`
4. ✅ Database is readable: `sqlite3 data/seed_server.db "SELECT COUNT(*) FROM users;"`
5. ✅ Disk space available: `df -h`
6. ✅ Memory not exhausted: `free -h`
7. ✅ No critical errors in logs: `grep CRITICAL logs/server.log`

### Common Issues

**Issue: "Database is locked"**
```
Solution:
- SQLite only supports one writer at a time
- Check for long-running transactions
- Increase timeout: DATABASE_TIMEOUT=30
- Consider PostgreSQL for high concurrency
```

**Issue: "LLM API rate limit exceeded"**
```
Solution:
- Check rate limit settings in settings.py
- Increase limits: GEMINI_MAX_REQUESTS_PER_MINUTE=100
- Enable request queuing: JOB_QUEUE_ENABLED=true
- Implement exponential backoff
```

**Issue: "Redis connection pool exhausted"**
```
Solution:
- Increase pool size: REDIS_MAX_CONNECTIONS=100
- Check for connection leaks
- Monitor active connections: redis-cli client list
- Restart server to reset pool
```

**Issue: "Server not responding"**
```
Solution:
- Check if process is running: ps aux | grep uvicorn
- Check ports: netstat -tulpn | grep 8000
- Check firewall: sudo ufw status
- Review logs for startup errors
```

### Performance Profiling

**Enable profiling:**
```python
# Add to main.py for temporary profiling
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()
# ... run operations ...
profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

**Memory profiling:**
```bash
# Install memory_profiler
pip install memory-profiler

# Profile specific endpoint
python -m memory_profiler app/diagnostic_engine.py
```

---

## Backup & Recovery

### Backup Schedule

**Recommended schedule:**
- **Hourly**: Automated incremental backups (last 24 hours)
- **Daily**: Full backups (last 30 days)
- **Weekly**: Full backups (last 12 weeks)
- **Monthly**: Archive backups (indefinite)

**Cron configuration:**
```bash
# Hourly backup
0 * * * * /path/to/seed_server/scripts/backup_database.sh

# Daily backup at 2 AM
0 2 * * * /path/to/seed_server/scripts/backup_database.sh

# Weekly cleanup
0 3 * * 0 find /path/to/backups -name "*.db.gz" -mtime +90 -delete
```

### Recovery Procedures

**Full recovery from catastrophic failure:**
```bash
# 1. Provision new server
# 2. Install dependencies
pip install -r requirements.txt

# 3. Restore configuration
cp .env.backup .env

# 4. Restore latest backup
./scripts/restore_database.sh data/backups/seed_server_20260112_143000.db.gz

# 5. Verify integrity
sqlite3 data/seed_server.db "PRAGMA integrity_check;"

# 6. Run migrations if needed
alembic upgrade head

# 7. Start server
systemctl start seed-server

# 8. Verify functionality
curl http://localhost:8000/health
pytest tests/test_critical_paths.py
```

### Disaster Recovery Plan

**RPO (Recovery Point Objective):** 1 hour  
**RTO (Recovery Time Objective):** 15 minutes

**Backup locations:**
- Local: `data/backups/`
- Cloud: S3/Azure Blob (optional)
- Off-site: Remote server (recommended)

---

## Performance Tuning

### Database Optimization

**Add indexes for common queries:**
```sql
CREATE INDEX IF NOT EXISTS idx_lessons_user_id ON lessons(user_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_diagnostics_created_at ON diagnostics(created_at);
```

**Enable WAL mode (better concurrency):**
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;  -- 64MB cache
```

### Redis Optimization

**Configuration:**
```conf
# redis.conf
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
save 300 10
save 60 10000
```

### Worker Scaling

**Calculate optimal worker count:**
```
Workers = (2 × CPU cores) + 1
```

**Docker Compose scaling:**
```bash
docker-compose up -d --scale worker=4
```

### Rate Limiting

**Adjust based on load:**
```python
# settings.py
RATE_LIMIT_PER_MINUTE = 100  # Increase for high traffic
RATE_LIMIT_BURST = 20        # Allow burst traffic
```

---

## On-Call Procedures

### Escalation Path

1. **Level 1**: Automated alerts → Slack/PagerDuty
2. **Level 2**: On-call engineer investigates
3. **Level 3**: Senior engineer if unresolved in 30 minutes
4. **Level 4**: Team lead if service down > 1 hour

### Emergency Contacts

- **On-call rotation**: PagerDuty schedule
- **Slack channel**: #seed-server-incidents
- **Team lead**: [Contact info]
- **Infrastructure team**: [Contact info]

### Incident Communication

**Template for status updates:**
```
[INCIDENT] Seed Server - High Error Rate

Status: Investigating
Impact: 15% of requests failing
Started: 2026-01-12 14:30 UTC
ETA: 15 minutes

Actions taken:
- Identified database lock contention
- Restarting server
- Monitoring recovery

Next update: 14:45 UTC
```

---

## Maintenance Windows

### Planned Maintenance

**Procedure:**
1. Announce 24 hours in advance
2. Schedule during low-traffic period (2-4 AM UTC)
3. Enable maintenance mode
4. Perform updates/migrations
5. Verify functionality
6. Disable maintenance mode
7. Monitor for issues

**Maintenance mode:**
```python
# Set in .env
MAINTENANCE_MODE=true

# Server returns 503 with message
{
  "detail": "Server is currently under maintenance. Expected completion: 03:00 UTC"
}
```

---

## Appendix

### Useful Commands Reference

```bash
# Quick diagnostics
./scripts/quick_health_check.sh

# Database size and stats
sqlite3 data/seed_server.db ".dbinfo"

# Redis memory usage
redis-cli INFO memory | grep used_memory_human

# Top 10 slowest endpoints
grep "duration_ms" logs/server.log | sort -k5 -rn | head -10

# Count requests by status code
awk '{print $9}' logs/access.log | sort | uniq -c | sort -rn
```

### Environment Variables Quick Reference

See [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) for complete list.

### Related Documentation

- [Database Migration Strategy](DATABASE_MIGRATION_STRATEGY.md)
- [Configuration Reference](CONFIGURATION_REFERENCE.md)
- [Server Capabilities](SERVER_CAPABILITIES_INVENTORY.md)
- [Monitoring Setup](../monitoring/MONITORING_SETUP.md)
