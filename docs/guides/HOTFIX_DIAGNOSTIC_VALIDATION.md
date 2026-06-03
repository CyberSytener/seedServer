# Hotfix: Diagnostic Validation NoneType Error

**Date:** January 10, 2026  
**Issue:** Diagnostic test generation timing out after 50+ seconds  
**Root Cause:** Validation error causing retries (3 attempts) during item generation

## Problem

Desktop client was experiencing timeouts on `POST /v1/learning/diagnostic/start`:
- Expected: 35-45 seconds
- Actual: 50+ seconds (timeout)
- Error: `TypeError: argument of type 'NoneType' is not iterable`

### Error Details

```python
File "/app/app/diagnostic_engine.py", line 95, in validate_diagnostic_item
    has_blank = "_____" in sentence or "__" in sentence or "_____" in prompt or "__" in prompt
TypeError: argument of type 'NoneType' is not iterable
```

The validation code was checking if blank markers existed in `sentence` or `prompt`, but these could be `None` (not just empty strings), causing the `in` operator to fail.

### Impact

- First LLM generation attempt: ~36s
- Validation fails → Retry 1: ~34s
- Validation fails → Retry 2: ~34s
- Total: 104+ seconds → Desktop timeout at 50s

## Solution

Fixed validation in `app/diagnostic_engine.py` line 88-93:

**Before:**
```python
sentence = context.get("sentence", "")
prompt = item.get("prompt", "")
```

**After:**
```python
sentence = context.get("sentence") or ""
prompt = item.get("prompt") or ""
```

This ensures `None` values are converted to empty strings before using the `in` operator.

## Testing

After fix:
- ✅ Test 1: 32.8 seconds (no retries)
- ✅ Test 2: 33.7 seconds (no retries)
- ✅ No validation errors in logs
- ✅ Desktop client receives response within 50s timeout

## Related to Desktop Auth Changes

Desktop team fixed session consistency by:
- Using `getApiKey()` instead of `ensureUser()` during diagnostic flow
- Maintaining same API key throughout entire session
- No mid-session user creation on 401 errors

This auth fix + server validation fix = stable diagnostic experience.

## Files Modified

- `app/diagnostic_engine.py` (line 88-89)

## Deployment

```bash
docker-compose up -d --build
```

No database migrations or config changes required.
