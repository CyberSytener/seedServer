# Desktop Client Authentication Fix

**Issue**: Desktop client fails with 401 "invalid api key" when calling `/v1/lessons/generate`

## Root Cause

Desktop client is **NOT sending the `X-User-ID` header** in lesson generation requests. The server requires authentication on ALL endpoints, including lesson generation.

## Error in Client

```typescript
// ❌ WRONG: No X-User-ID header
fetch('http://localhost:8000/v1/lessons/generate', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json'
    // Missing: 'X-User-ID': userId
  },
  body: JSON.stringify({...})
})
```

## Fix Required

Desktop client must include `X-User-ID` header in **ALL API requests**:

```typescript
// ✅ CORRECT: Include X-User-ID header
fetch('http://localhost:8000/v1/lessons/generate', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-User-ID': userId  // ← Required for authentication!
  },
  body: JSON.stringify({...})
})
```

## Where to Fix in Desktop Client

### Option 1: Add to lessonService.ts

Update `generateLessonFromServer()` function:

```typescript
// lessonService.ts
async function generateLessonFromServer(request: LessonGenerateRequest): Promise<Lesson> {
  const userId = getUserId(); // Get from your auth context
  
  const response = await fetch(`${API_BASE_URL}/v1/lessons/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': userId  // ← Add this!
    },
    body: JSON.stringify(request)
  });
  
  if (!response.ok) {
    throw new Error(`Failed to generate lesson: ${response.status}`);
  }
  
  return await response.json();
}
```

### Option 2: Create HTTP Client Wrapper (Recommended)

Create a centralized API client that automatically adds headers:

```typescript
// api/client.ts
export class ApiClient {
  private baseUrl: string;
  private userId: string;
  
  constructor(baseUrl: string, userId: string) {
    this.baseUrl = baseUrl;
    this.userId = userId;
  }
  
  private getHeaders(): HeadersInit {
    return {
      'Content-Type': 'application/json',
      'X-User-ID': this.userId  // ← Always included
    };
  }
  
  async post<T>(endpoint: string, data: any): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(data)
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(`API Error: ${response.status} ${JSON.stringify(error)}`);
    }
    
    return await response.json();
  }
  
  async get<T>(endpoint: string): Promise<T> {
    const response = await fetch(`${this.baseUrl}${endpoint}`, {
      method: 'GET',
      headers: this.getHeaders()
    });
    
    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }
    
    return await response.json();
  }
}

// Usage in lessonService.ts
const apiClient = new ApiClient('http://localhost:8000', userId);

async function generateLessonFromServer(request: LessonGenerateRequest): Promise<Lesson> {
  return await apiClient.post<Lesson>('/v1/lessons/generate', request);
}
```

## Quick Test

After fixing, verify with curl:

```bash
# Should succeed (200 OK)
curl -X POST http://localhost:8000/v1/lessons/generate \
  -H "Content-Type: application/json" \
  -H "X-User-ID: desktop_test_user" \
  -d '{
    "targetLang": "en",
    "nativeLang": "ru",
    "level": "A2",
    "mode": "mixed",
    "lessonLength": 10
  }'
```

## Why This Happened

1. Server requires authentication on all endpoints
2. Desktop client was working before because:
   - Other endpoints (diagnostics) were already sending X-User-ID
   - Lesson generation was added later without auth header
3. Server's legacy mode (`SEED_ENABLE_LEGACY_X_USER_ID=true`) allows X-User-ID for development

## Checklist for Desktop Client

- [ ] Update `lessonService.ts` to include `X-User-ID` header
- [ ] Update `diagnosticService.ts` to include `X-User-ID` header
- [ ] Update any other API calls to include `X-User-ID` header
- [ ] Consider creating centralized API client wrapper
- [ ] Test all API endpoints after changes

## Related Files

- Server: `app/auth.py` (authentication logic)
- Server: `app/main.py` (endpoint handlers)
- Client: `lessonService.ts` (needs fix)
- Client: `diagnosticService.ts` (check if has X-User-ID)

## Notes

- Legacy mode (`X-User-ID`) is for development only
- Production should use proper API keys (Bearer token)
- Server now auto-creates user records for X-User-ID auth
- All endpoints require authentication (no anonymous access)

---

**Action Required**: Update desktop client to include `X-User-ID: ${userId}` in all API request headers
