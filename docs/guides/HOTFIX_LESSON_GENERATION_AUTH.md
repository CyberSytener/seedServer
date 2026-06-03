# Hotfix: Lesson Generation Auth Issue (X-User-ID)

**Date**: 2026-01-10  
**Status**: ✅ Fixed  
**Severity**: High  
**Reporter**: Desktop Client  

## Issue

Desktop client reported `401 Unauthorized` errors when calling `POST /v1/lessons/generate`. Investigation revealed actual error was `500 Internal Server Error` with `FOREIGN KEY constraint failed`.

### Error Details

```
sqlite3.IntegrityError: FOREIGN KEY constraint failed
```

**Root Cause**: When using legacy auth mode (`X-User-ID` header), authentication succeeded but user record was NOT created in `users` table. When lesson generation tried to insert into `lessons` table with FOREIGN KEY to `users(id)`, database rejected the operation.

## Timeline

1. Desktop client reports 401 error when generating lessons
2. Created test script to reproduce issue
3. Found auth works but 500 error occurs
4. Checked logs: FOREIGN KEY constraint failed
5. Analyzed `lessons` table schema → FK to `users(id)`
6. Examined `auth.py` → legacy mode doesn't create user record
7. Fixed by auto-creating user on first X-User-ID auth

## Root Cause Analysis

### Database Schema
```sql
CREATE TABLE lessons (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  lesson_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

### Original Auth Code
```python
# app/auth.py (before fix)
if settings.enable_legacy_x_user_id:
    legacy_user = request.headers.get("X-User-ID")
    if legacy_user:
        return AuthContext(user_id=legacy_user.strip(), is_admin=False)
        # Problem: User might not exist in database!
```

When desktop client used `X-User-ID` header:
- ✅ Authentication passed
- ✅ Lesson generated successfully (10 tasks)
- ❌ Database INSERT failed with FK constraint error
- ❌ API returned 500 error to client

## Solution

Modified `app/auth.py` to auto-create user record when using `X-User-ID` auth:

```python
# app/auth.py (after fix)
if settings.enable_legacy_x_user_id:
    legacy_user = request.headers.get("X-User-ID")
    if legacy_user:
        user_id = legacy_user.strip()
        # Ensure user exists in database for foreign key constraints
        existing = db.fetchone("SELECT id FROM users WHERE id = ?", (user_id,))
        if not existing:
            db.execute("INSERT INTO users(id) VALUES(?)", (user_id,))
        return AuthContext(user_id=user_id, is_admin=False)
```

## Verification

### Test Script
Created `test_lesson_generation_auth.ps1` to verify fix:

```powershell
# Test 1: No auth → 401 (expected)
# Test 2: With X-User-ID → 200 OK (fixed!)
```

### Test Results (After Fix)
```
Test 1: No authentication
✘ Failed with status 401 (expected)

Test 2: With X-User-ID header (legacy mode)
✓ Success! Lesson generated:
   Lesson ID: lesson_Y9zBLokNZ1YyQw
   Tasks: 10
```

## Impact

- **Who was affected**: Desktop clients using legacy X-User-ID auth
- **When**: All lesson generation attempts since FOREIGN KEY was added to lessons table
- **Workaround**: None available (blocking issue)
- **Fix deployed**: 2026-01-10

## Files Changed

1. `app/auth.py` - Added user auto-creation in legacy mode
2. `test_lesson_generation_auth.ps1` - Created test script

## Deployment Steps

```bash
# 1. Code fix already applied
# 2. Rebuild Docker image
docker-compose build api

# 3. Restart API service
docker-compose up -d api

# 4. Verify fix
.\test_lesson_generation_auth.ps1
```

## Prevention

**Future Considerations**:
1. Add integration tests for legacy auth mode
2. Consider migrating desktop client to proper API key auth
3. Add database constraint checks in CI/CD pipeline
4. Log warnings when legacy mode is used

## Related Issues

- Adaptive learning implementation (completed)
- Desktop client authentication (resolved)

## Notes

- Legacy mode (`X-User-ID`) should only be used during development
- Production deployments should enforce API key authentication
- Consider deprecating legacy mode after desktop client migrates

---

**Status**: ✅ Resolved
**Verified**: Desktop client successfully generates lessons with X-User-ID auth
