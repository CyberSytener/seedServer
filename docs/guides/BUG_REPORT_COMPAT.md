# Bug Reports API - Backward Compatibility

## Authentication

The `/v1/feedback/bug-reports` endpoint accepts API keys via **two methods**:

### Method 1: `x-api-key` Header (Recommended)
```http
POST /v1/feedback/bug-reports
x-api-key: seed_abc123...
Content-Type: application/json
```

### Method 2: `Authorization: Bearer` Header (Legacy Support)
```http
POST /v1/feedback/bug-reports
Authorization: Bearer seed_abc123...
Content-Type: application/json
```

Both methods use the same authentication logic (`authenticate()` in `auth.py`). Security is not weakened - the same key validation applies to both headers.

---

## Debug Field Compatibility

The `debug` object in `BugReportRequest` accepts **two field names** for the capture timestamp:

### Canonical Field: `captureAt` (Recommended)
```json
{
  "debug": {
    "includeDetails": true,
    "captureAt": "2026-01-10T12:34:56Z"
  }
}
```

### Legacy Field: `capturedAt` (Backward Compatible)
```json
{
  "debug": {
    "includeDetails": true,
    "capturedAt": "2026-01-10T12:34:56Z"
  }
}
```

### Normalization Rules

1. **If only `captureAt` is present:** Used as-is (canonical)
2. **If only `capturedAt` is present:** Automatically renamed to `captureAt` before storage
3. **If both are present:** `captureAt` takes precedence, `capturedAt` is removed

### Storage Format

The stored `payload_json` in the database **always uses the canonical field name** (`captureAt`), ensuring consistency for AI analysis and future processing.

**Example stored JSON:**
```json
{
  "debug": {
    "includeDetails": true,
    "captureAt": "2026-01-10T12:34:56Z"
  }
}
```

---

## Implementation Details

### File: `app/main.py`

**Normalization logic** in `/v1/feedback/bug-reports` endpoint:

```python
# Normalize debug field for backward compatibility
if req.debug:
    debug_normalized = dict(req.debug)
    if "capturedAt" in debug_normalized and "captureAt" not in debug_normalized:
        debug_normalized["captureAt"] = debug_normalized.pop("capturedAt")
    req.debug = debug_normalized
```

This ensures:
- Old clients using `capturedAt` continue to work
- New clients can use the canonical `captureAt`
- Database stores normalized format for consistency
- No breaking changes to existing deployments

---

## Testing

Run the compatibility test suite:

```bash
# Update API_KEY in test_bug_report_compat.py first
python test_bug_report_compat.py
```

**Tests included:**
1. ✓ `x-api-key` header with `captureAt` field
2. ✓ `Authorization: Bearer` header with `capturedAt` field (legacy)
3. ✓ Both fields present (captureAt takes precedence)

---

## Migration Path

### For Desktop Clients

**Current (v0.9.x):** Using `capturedAt`
```typescript
// Old code (still works)
debug: {
  capturedAt: new Date().toISOString()
}
```

**Future (v1.0+):** Migrate to `captureAt`
```typescript
// New code (recommended)
debug: {
  captureAt: new Date().toISOString()
}
```

No rush to migrate - both formats are supported indefinitely for backward compatibility.

---

## Response Format

Both authentication methods and field name variants return the **same response format**:

```json
{
  "ok": true,
  "reportId": "bug_a1b2c3d4e5f6g7h8",
  "receivedAt": "2026-01-10T12:34:56.789Z"
}
```

---

## Security Notes

- ✓ Both auth methods validate against the same API key hash
- ✓ Same rate limiting applied regardless of header used
- ✓ User context extracted consistently from both methods
- ✓ No security downgrade or bypass introduced

---

## Why This Approach?

1. **Zero Breaking Changes:** Existing Desktop deployments continue working
2. **Clean Storage:** Database stores canonical format for consistency
3. **Future-Proof:** New clients can adopt canonical field names
4. **AI-Readable:** Normalized storage improves analysis/debugging
5. **Security Maintained:** Same auth validation for all requests
