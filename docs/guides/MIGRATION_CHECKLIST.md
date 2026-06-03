# Migration Checklist: Async LLM Implementation

Use this checklist when deploying the async LLM improvements to production.

## ✅ Pre-Deployment

### 1. Dependencies
- [ ] Verify `httpx==0.27.0` in requirements.txt
- [ ] Run `pip install -r requirements.txt`
- [ ] Confirm no dependency conflicts

### 2. Configuration
- [ ] Verify `GEMINI_API_KEY` is set
- [ ] Verify `OPENAI_API_KEY` is set (if using OpenAI)
- [ ] Verify `REDIS_URL` is set
- [ ] Check `.env` file has all required vars

### 3. Testing
- [ ] Run example client: `python example_async_client.py`
- [ ] Test streaming endpoint with curl
- [ ] Test job queue submission
- [ ] Verify SSE events are received
- [ ] Check Redis connectivity

## 🚀 Deployment

### 4. Staging Deployment
- [ ] Deploy to staging environment
- [ ] Run smoke tests on all new endpoints
- [ ] Monitor metrics for 24 hours
- [ ] Verify no errors in logs
- [ ] Test with real workload (10-100 requests)

### 5. Load Testing
- [ ] Test 100 concurrent streaming requests
- [ ] Test 500 concurrent requests (if possible)
- [ ] Verify connection pool doesn't max out
- [ ] Check memory usage is stable
- [ ] Confirm no thread exhaustion

### 6. Infrastructure
- [ ] If using nginx, disable proxy buffering for `/stream` endpoints
- [ ] Configure load balancer for SSE keep-alive
- [ ] Ensure firewall allows long-running connections
- [ ] Check CDN settings don't interfere with streaming

**Nginx config for streaming:**
```nginx
location ~ ^/v1/.*/stream$ {
    proxy_pass http://backend;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
    proxy_read_timeout 300s;
}
```

## 📊 Monitoring Setup

### 7. Metrics
- [ ] Add dashboard for streaming latency
- [ ] Monitor connection pool usage
- [ ] Track queue depth over time
- [ ] Alert on worker failures
- [ ] Monitor SSE connection count

### 8. Logging
- [ ] Verify streaming events are logged
- [ ] Check job queue events are tracked
- [ ] Confirm error handling logs properly
- [ ] Test log aggregation (if using)

## 🎯 Production Deployment

### 9. Gradual Rollout
- [ ] Deploy to 10% of production traffic
- [ ] Monitor for 2 hours
- [ ] If stable, increase to 50%
- [ ] Monitor for 4 hours
- [ ] If stable, deploy to 100%

### 10. Feature Flags (Optional)
- [ ] Create flag for streaming endpoints
- [ ] Create flag for job queue API
- [ ] Set defaults to enabled
- [ ] Test toggle in production

### 11. Documentation
- [ ] Update API documentation
- [ ] Notify client teams of new endpoints
- [ ] Share migration guide
- [ ] Update SDKs (if applicable)

## 🔧 Post-Deployment

### 12. Client Migration
- [ ] Provide example code to client teams
- [ ] Schedule migration timeline
- [ ] Support gradual adoption
- [ ] Keep old endpoints for 3-6 months

### 13. Performance Validation
- [ ] Measure actual TTFB (should be <1s)
- [ ] Measure throughput improvement
- [ ] Collect user feedback
- [ ] Compare before/after metrics

### 14. Optimization
- [ ] Tune connection pool if needed
- [ ] Adjust worker count based on load
- [ ] Optimize queue priorities
- [ ] Fine-tune timeouts

## 🐛 Rollback Plan

### 15. Rollback Preparation
- [ ] Document rollback procedure
- [ ] Test rollback in staging
- [ ] Keep old code branch available
- [ ] Have rollback script ready

### 16. Rollback Triggers
- [ ] Error rate > 5%
- [ ] Latency > 2x baseline
- [ ] Memory leak detected
- [ ] Critical bug found

### 17. Rollback Steps
```bash
# 1. Disable new endpoints (if using feature flags)
# 2. Redeploy previous version
git checkout previous-release
docker build -t seed-server:rollback .
docker-compose up -d

# 3. Verify old endpoints working
curl http://localhost:8000/v1/lessons/generate

# 4. Monitor recovery
```

## 📈 Success Metrics

### 18. KPIs to Track
- [ ] Time to First Byte (target: <1s)
- [ ] P95 latency (target: <2s)
- [ ] Error rate (target: <1%)
- [ ] Concurrent requests (target: 500+)
- [ ] User satisfaction (survey/NPS)

### 19. Business Metrics
- [ ] Conversion rate (should improve)
- [ ] Session duration (should increase)
- [ ] Bounce rate (should decrease)
- [ ] Support tickets (should decrease)

## 🎓 Training & Support

### 20. Team Enablement
- [ ] Train frontend team on SSE
- [ ] Train backend team on async patterns
- [ ] Share troubleshooting guide
- [ ] Setup support rotation

### 21. Documentation Updates
- [ ] API docs updated
- [ ] Architecture docs updated
- [ ] Runbook created
- [ ] FAQ published

## ✅ Sign-Off

### Final Checklist
- [ ] All tests passing
- [ ] Performance validated
- [ ] Documentation complete
- [ ] Team trained
- [ ] Monitoring active
- [ ] Rollback plan tested

### Approvals
- [ ] Tech Lead approval
- [ ] DevOps approval
- [ ] Product Manager approval
- [ ] QA sign-off

---

## 📞 Support Contacts

**During deployment:**
- On-call: [Your team's contact]
- Escalation: [Manager contact]
- Infrastructure: [DevOps contact]

**Post-deployment:**
- General support: [Support channel]
- Bug reports: [Issue tracker]
- Questions: [Team channel]

---

## 📝 Deployment Notes

**Date:** _________________  
**Environment:** _________________  
**Version:** _________________  
**Deployed by:** _________________  

**Issues encountered:**
- 
- 
- 

**Resolution:**
- 
- 
- 

**Lessons learned:**
- 
- 
- 

---

**Status:** ⬜ Not Started | 🟡 In Progress | ✅ Complete | ❌ Blocked
