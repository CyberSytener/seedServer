# Diagnostic V0 - Performance & Timeout Configuration

## Current Performance Characteristics

### Endpoint Response Times

| Endpoint | Typical | Max | Notes |
|----------|---------|-----|-------|
| POST `/v1/learning/diagnostic/start` | 30-45s | 45s timeout | Generates 25 items via LLM |
| POST `/v1/learning/diagnostic/attempt` | <100ms | N/A | Local evaluation only |
| POST `/v1/learning/diagnostic/next` | <50ms | N/A | Database query |
| POST `/v1/learning/diagnostic/finish` | ~200ms | N/A | Scoring calculation |

### Timeout Configuration

**LLM Request Timeout:** 45 seconds
- Location: `app/diagnostic_engine.py` line ~205
- Purpose: Prevent indefinite hangs during item generation
- Behavior: Fails fast if Gemini doesn't respond in time
- Retries: 3 attempts with exponential backoff

**HTTP Client Timeout:** Configurable (default 60s)
- Location: `app/router.py` execute_llm_request
- Purpose: Network-level timeout for all LLM providers
- Can be overridden per-call

## Error Handling

### Timeout Errors (504 Gateway Timeout)
```json
{
  "detail": "item_generation_timeout"
}
```
**Cause:** LLM failed to respond within 45 seconds  
**Desktop Action:** Show error message, allow retry

### Generation Errors (502 Bad Gateway)
```json
{
  "detail": "item_generation_failed: <specific error>"
}
```
**Cause:** LLM returned invalid JSON or validation failed after 3 retries  
**Desktop Action:** Show error message with details, allow retry

### Internal Errors (500)
```json
{
  "detail": "internal_server_error"
}
```
**Cause:** Unexpected server error  
**Desktop Action:** Show generic error, log for debugging

## Production Recommendations

### For Desktop Client

1. **Show Loading Indicator**
   - Display "Generating placement test..." message
   - Show spinner or progress animation
   - Expected wait: 30-45 seconds
   - Don't let request timeout client-side before 50 seconds

2. **Handle Timeouts Gracefully**
   ```typescript
   try {
     const response = await fetch('/v1/learning/diagnostic/start', {
       method: 'POST',
       headers: { 'Authorization': `Bearer ${apiKey}` },
       body: JSON.stringify(payload),
       signal: AbortSignal.timeout(50000) // 50s client timeout
     });
   } catch (error) {
     if (error.name === 'TimeoutError') {
       // Show "Taking longer than expected, please retry"
     }
   }
   ```

3. **Retry Strategy**
   - Allow user to retry on timeout/502 errors
   - Don't auto-retry (wastes LLM quota)
   - Consider showing "Try a different language pair" on repeated failures

### For Server Operators

1. **Monitor LLM Response Times**
   - Check logs for `[DIAGNOSTIC]` entries
   - Alert if >40% requests take >40s
   - Alert if >5% timeout (504 errors)

2. **Log Analysis**
   ```bash
   # Check diagnostic generation times
   docker-compose logs api | grep "\[DIAGNOSTIC\]" | grep "duration_ms"
   
   # Check timeout rate
   docker-compose logs api | grep "item_generation_timeout" | wc -l
   ```

3. **Capacity Planning**
   - Each `/start` request: ~40s LLM time
   - Max concurrent: ~3 requests/minute/API key (Gemini rate limits)
   - Consider multiple API keys for load distribution

## Future Improvements (V1 Roadmap)

### Option 1: Pre-Generated Item Pools ⭐ RECOMMENDED
**Pros:**
- Instant response (<200ms)
- No LLM costs per session
- Consistent quality
- No timeout issues

**Cons:**
- Need to pre-generate for each language pair × CEFR level
- Storage requirements (~100 items × 50 language pairs = 5000 items)
- Less variability (but acceptable for diagnostics)

**Implementation:**
1. Generate 100 items per language pair offline
2. Store in `diagnostic_item_pool` table
3. `/start` endpoint selects random 25 items from pool
4. Regenerate pool weekly/monthly

### Option 2: Async Generation with Status Polling
**Pros:**
- Immediate response (session created)
- Progressive user experience
- Handles timeouts gracefully

**Cons:**
- More complex frontend
- Need status polling endpoint
- Session starts incomplete

**Implementation:**
```python
# POST /v1/learning/diagnostic/start
# Returns immediately:
{
  "sessionId": "diag_abc",
  "status": "generating",
  "pollUrl": "/v1/learning/diagnostic/status/diag_abc"
}

# GET /v1/learning/diagnostic/status/{sessionId}
# Returns:
{
  "status": "ready|generating|failed",
  "itemsReady": 25,
  "totalItems": 25,
  "error": null
}
```

### Option 3: Progressive Delivery (Hybrid)
**Pros:**
- Quick initial response (5 items in ~8s)
- Can start test while rest generate
- Best UX balance

**Cons:**
- Most complex implementation
- Need background task queue
- Partial failure scenarios

**Implementation:**
1. Generate first 5 items synchronously (~8s)
2. Return session with 5 items
3. Generate remaining 20 items in background worker
4. Use `/next` endpoint to poll for new items

## Current V0 Trade-offs

**Why V0 is Synchronous:**
- ✅ Simplest implementation
- ✅ No background job infrastructure needed
- ✅ Deterministic behavior (either works or fails)
- ✅ Easy to debug
- ❌ Slow first response (30-45s)
- ❌ Poor UX without proper loading indicator

**Acceptable for:**
- MVP/beta testing
- Low concurrent user load (<10 simultaneous diagnostics)
- Users who understand "generating test" takes time

**Not acceptable for:**
- High-traffic production (>50 concurrent users)
- Mobile with poor network (timeout issues)
- Impatient users expecting instant results

## Monitoring & Alerts

### Key Metrics to Track

1. **P50/P95/P99 Response Times**
   ```
   Target:
   - P50: <35s
   - P95: <42s
   - P99: <45s
   ```

2. **Timeout Rate**
   ```
   Target: <2% of requests
   Alert: >5% in 5-minute window
   ```

3. **Generation Failure Rate**
   ```
   Target: <1% (validation failures)
   Alert: >3% in 5-minute window
   ```

4. **Concurrent Sessions**
   ```
   Monitor: Active diagnostic sessions
   Alert: >20 concurrent (capacity warning)
   ```

### Structured Log Fields

All diagnostic operations log with these fields:
```json
{
  "message": "[DIAGNOSTIC] Session started",
  "session_id": "diag_abc123",
  "user_id": "user_xyz",
  "native_lang": "English",
  "target_lang": "Spanish",
  "items_count": 25,
  "duration_ms": 35421,
  "status": "ok|timeout|error",
  "error_type": "timeout|validation|json_decode|unexpected"
}
```

Use these for dashboards and alerting.

---

## Decision: When to Migrate from V0

**Stay on V0 if:**
- <50 diagnostic sessions per day
- Users are patient (educational context)
- MVP/beta testing phase
- Budget constraints (pre-generation costs)

**Migrate to V1 (pooled items) if:**
- >100 diagnostic sessions per day
- Timeout rate >3%
- User complaints about wait time
- Multiple language pairs needed at scale

**Estimated Migration Effort:**
- Pre-generation: 2-3 days dev + 1 day testing
- Async generation: 3-5 days dev + 2 days testing
- Progressive delivery: 5-7 days dev + 3 days testing

---

*Last Updated: 2026-01-09*  
*Status: V0 in production with known performance limitations*
