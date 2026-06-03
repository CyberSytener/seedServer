# Diagnostic Session 404 Error - Troubleshooting Guide

## Error Message
```
Failed to get next item: 404 {"detail":"session_not_found"}
```

## Common Causes

### 1. **Session Ownership Mismatch** (Most Likely)
The session exists but was created by a different user ID.

**What to check:**
- Are you using the same API key/auth token for both `/start` and `/next`?
- Did you switch users or API keys between requests?
- Is the Desktop caching an old session ID from a previous user?

**Server now logs this as:**
```json
{
  "message": "[DIAGNOSTIC] Session found but belongs to different user",
  "requested_session_id": "diag_abc123",
  "requesting_user_id": "user_xyz",
  "actual_session_owner": "user_abc"
}
```

### 2. **Session Doesn't Exist**
The session was never created or has been deleted.

**What to check:**
- Did the `/start` request succeed and return a `sessionId`?
- Are you sending the correct `sessionId` in `/next` and `/attempt`?
- Check for typos in the session ID

**Server now logs this as:**
```json
{
  "message": "[DIAGNOSTIC] Session does not exist in database",
  "requested_session_id": "diag_abc123",
  "requesting_user_id": "user_xyz"
}
```

### 3. **Session Expired or Abandoned**
The session exists but has been marked as abandoned or deleted.

**What to check:**
- Session status in database
- Any cleanup processes that might be removing old sessions

## Debugging Steps

### Step 1: Check Desktop Request Flow
```typescript
// Verify you're storing the sessionId correctly
const startResponse = await api.post('/v1/learning/diagnostic/start', {
  nativeLanguage: 'en',
  targetLanguage: 'es',
  startLevelGuess: 'A2'
});

const sessionId = startResponse.data.sessionId;
console.log('Session ID:', sessionId);

// Make sure you're using the SAME sessionId
const nextResponse = await api.post('/v1/learning/diagnostic/next', {
  sessionId: sessionId  // <-- Must match exactly
});
```

### Step 2: Check Authentication
```typescript
// Verify API key is consistent across requests
const headers = {
  Authorization: `Bearer ${API_KEY}`  // <-- Must be same key
};

// All diagnostic requests should use the same auth
await api.post('/start', data, { headers });
await api.post('/attempt', data, { headers });
await api.post('/next', data, { headers });
```

### Step 3: Check Server Logs
```powershell
# View diagnostic logs with context
docker-compose logs api | Select-String "DIAGNOSTIC" | Select-Object -Last 50

# Look for these patterns:
# - "Session started" with sessionId
# - "/next request" with sessionId and user_id
# - "Session found but belongs to different user" (ownership mismatch)
# - "Session does not exist in database" (not found)
```

### Step 4: Verify Database State
```sql
-- Check if session exists
SELECT id, user_id, status, created_at 
FROM diagnostic_sessions 
WHERE id = 'diag_abc123';

-- Check session items
SELECT COUNT(*) 
FROM diagnostic_session_items 
WHERE session_id = 'diag_abc123';
```

## Enhanced Logging (Now Live)

The server now logs detailed information for every `/next` and `/attempt` request:

**Successful request:**
```json
{
  "message": "[DIAGNOSTIC] /next request",
  "session_id": "diag_abc123",
  "user_id": "user_xyz"
}
```

**Failed request (ownership mismatch):**
```json
{
  "message": "[DIAGNOSTIC] Session found but belongs to different user",
  "requested_session_id": "diag_abc123",
  "requesting_user_id": "user_xyz",
  "actual_session_owner": "user_abc",
  "session_status": "running"
}
```

**Failed request (not found):**
```json
{
  "message": "[DIAGNOSTIC] Session does not exist in database",
  "requested_session_id": "diag_abc123",
  "requesting_user_id": "user_xyz"
}
```

## Quick Fixes

### Fix 1: Ensure Consistent Authentication
```typescript
// Create a single API client instance with auth
const apiClient = axios.create({
  baseURL: 'http://localhost:8000',
  headers: {
    Authorization: `Bearer ${API_KEY}`
  }
});

// Use same client for all requests
const startRes = await apiClient.post('/v1/learning/diagnostic/start', {...});
const nextRes = await apiClient.post('/v1/learning/diagnostic/next', {
  sessionId: startRes.data.sessionId
});
```

### Fix 2: Store Session ID Properly
```typescript
// Don't rely on component state that might reset
// Use persistent storage for session ID
localStorage.setItem('currentDiagnosticSession', sessionId);

// Later...
const sessionId = localStorage.getItem('currentDiagnosticSession');
```

### Fix 3: Handle Session Lifecycle
```typescript
// Clear session ID when starting new diagnostic
localStorage.removeItem('currentDiagnosticSession');

// Start new session
const response = await startDiagnostic();
localStorage.setItem('currentDiagnosticSession', response.sessionId);

// Always check if session exists before calling /next
if (!localStorage.getItem('currentDiagnosticSession')) {
  // Redirect to start new diagnostic
}
```

## Contact Server Team

If the issue persists after checking all above:
1. Provide server logs showing the error
2. Provide the exact `sessionId` causing issues
3. Provide the API key/user ID being used
4. Provide timestamps of `/start` and `/next` requests

We can then query the database to see what's happening.
