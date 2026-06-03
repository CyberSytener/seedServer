# Bug Reports API & Grading Fix Implementation

## Summary

This document describes the implementation of two key improvements to Seed Server:

1. **Fixed reorder_sentence grading** to handle punctuation and case differences
2. **Added Bug Reports API endpoint** for structured client feedback

---

## Part A: Fixed reorder_sentence Grading

### Problem
Client tokens often have no punctuation (e.g., `["I", "eat", "apples"]`), while the correct answer may include trailing punctuation (e.g., `"I eat apples."`). This caused correct answers to fail when compared with strict string equality.

### Solution
Implemented robust normalization specifically for `reorder_sentence` task types in the `evaluate_answer` function.

### Implementation Details

**File:** [app/diagnostic_session.py](app/diagnostic_session.py)

**Function:** `normalize_answer_reorder_sentence(text: str) -> str`

**Normalization Steps:**
1. **Unicode NFKC normalization** - Handles special characters and combining marks
2. **Strip leading/trailing whitespace**
3. **Collapse multiple spaces to single space** - Handles `"I  eat  apples"` → `"I eat apples"`
4. **Casefold** - Locale-aware lowercase (better than `.lower()` for international text)
5. **Remove trailing sentence punctuation** - Strips `. ! ? …` from end of string
6. **Final strip** - Clean up after punctuation removal

**Modified Function:** `evaluate_answer(item: DiagnosticItem, user_answer: str) -> tuple[bool, str]`

Added special handling:
```python
if item_type == "reorder_sentence":
    user_normalized = normalize_answer_reorder_sentence(user_answer)
    
    for accepted in accepted_answers:
        accepted_normalized = normalize_answer_reorder_sentence(accepted)
        if user_normalized == accepted_normalized:
            return True, accepted_answers[0]
```

### Test Cases Now Passing

| User Answer | Expected Answer | Result |
|-------------|----------------|---------|
| `"I eat apples"` | `"I eat apples."` | ✓ Correct |
| `"i eat apples"` | `"I eat apples."` | ✓ Correct |
| `"I  eat  apples"` | `"I eat apples."` | ✓ Correct |
| `"I eat apples"` | `"I eat apples!"` | ✓ Correct |
| `"I eat apples"` | `"I eat apples?"` | ✓ Correct |

### Backward Compatibility
- **Other task types unchanged** - Only affects `reorder_sentence`
- **Existing normalization preserved** - Standard `lower_trim` still used for `mcq`, `fill_blank`, etc.
- **No database schema changes**

---

## Part B: Bug Reports API

### Overview
New endpoint to receive structured bug reports from clients, with full context storage for debugging and analysis.

### Endpoint

**URL:** `POST /v1/feedback/bug-reports`

**Authentication:** Accepts API key via **two methods** (backward compatible):
- `x-api-key: <api-key>` header (recommended)
- `Authorization: Bearer <api-key>` header (legacy support)

Both methods validated identically - no security weakening.

**Rate Limiting:** Applied via standard rate limiting

### Request Model

**File:** [app/models.py](app/models.py)

**Model:** `BugReportRequest`

```python
{
  "kind": "grading_mismatch" | "ui_bug" | "content_bug" | "other",
  "severity": "minor" | "major",
  "userMessage": "Optional user description (max 5000 chars)",
  "context": {
    "feature": "diagnostic",
    "sessionId": "diag_abc123",
    "itemId": "item_456",
    "taskType": "reorder_sentence",
    "prompt": "Reorder these words...",
    "tokens": ["I", "eat", "apples"],
    "userAnswerRaw": "I eat apples",
    "correctAnswerShown": "I eat apples.",
    "serverResponse": {"correct": false}
  },
  "client": {
    "app": "seed-desktop",
    "appVersion": "1.0.0",
    "platform": "win32",
    "userAgent": "Mozilla/5.0...",
    "locale": "en-US",
    "timezone": "America/New_York"
  },
  "debug": {
    "includeDetails": true,
    "captureAt": "2026-01-10T12:34:56Z"  // Canonical field
    // Legacy: "capturedAt" also accepted, auto-normalized to "captureAt"
  }
}
```

**Note:** The `debug.captureAt` field accepts both `captureAt` (canonical) and `capturedAt` (legacy) for backward compatibility. Both are automatically normalized to `captureAt` before storage. See [BUG_REPORT_COMPAT.md](BUG_REPORT_COMPAT.md) for details.

### Response Model

**Model:** `BugReportResponse`

```json
{
  "ok": true,
  "reportId": "bug_a1b2c3d4e5f6g7h8",
  "receivedAt": "2026-01-10T12:34:56.789Z"
}
```

### Database Schema

**File:** [app/db.py](app/db.py)

**Table:** `bug_reports`

```sql
CREATE TABLE IF NOT EXISTS bug_reports (
  id TEXT PRIMARY KEY,              -- Format: bug_{uuid16}
  user_id TEXT NOT NULL,            -- From auth context
  kind TEXT NOT NULL,               -- Enum value
  severity TEXT NOT NULL,           -- Enum value
  payload_json TEXT NOT NULL,       -- Full request JSON (AI-readable)
  created_at TEXT NOT NULL,         -- ISO datetime
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX idx_bug_reports_user_id ON bug_reports(user_id);
CREATE INDEX idx_bug_reports_created_at ON bug_reports(created_at DESC);
CREATE INDEX idx_bug_reports_kind ON bug_reports(kind);
```

### Implementation

**File:** [app/main.py](app/main.py)

**Endpoint:** `/v1/feedback/bug-reports`

**Key Features:**
- Validates request with Pydantic models
- Generates unique report ID (`bug_{uuid16}`)
- Stores full request JSON in `payload_json` column (AI-readable format)
- Captures user_id from auth context
- Returns report ID and timestamp
- Comprehensive structured logging

### Usage Example

```bash
curl -X POST http://localhost:8000/v1/feedback/bug-reports \
  -H "x-api-key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "kind": "grading_mismatch",
    "severity": "major",
    "userMessage": "Expected correct but got wrong",
    "context": {
      "sessionId": "diag_123",
      "itemId": "item_456",
      "taskType": "reorder_sentence"
    },
    "client": {
      "app": "seed-desktop",
      "appVersion": "1.0.0"
    }
  }'
```

### Client Integration

Desktop app can call this endpoint whenever:
1. User reports a grading issue
2. UI bug occurs
3. Content appears incorrect
4. Any other feedback

No changes needed to existing Desktop code beyond adding the API call.

---

## Files Modified

### Modified Files

1. **[app/diagnostic_session.py](app/diagnostic_session.py)**
   - Added `normalize_answer_reorder_sentence()` function
   - Modified `evaluate_answer()` to use special normalization for `reorder_sentence`

2. **[app/models.py](app/models.py)**
   - Added `BugReportKind` enum
   - Added `BugReportSeverity` enum
   - Added `BugReportRequest` model
   - Added `BugReportResponse` model

3. **[app/db.py](app/db.py)**
   - Added `bug_reports` table schema
   - Added indexes for efficient querying

4. **[app/main.py](app/main.py)**
   - Imported bug report models
   - Added `/v1/feedback/bug-reports` endpoint
   - Added structured logging for bug reports

### New Files

5. **[test_bug_report.py](test_bug_report.py)**
   - Test script for bug reports endpoint
   - Local tests for normalization function

6. **[BUG_REPORTS_IMPLEMENTATION.md](BUG_REPORTS_IMPLEMENTATION.md)**
   - This documentation file

---

## Testing

### Running the Tests

1. **Test Normalization (Local):**
   ```bash
   python -c "from app.diagnostic_session import normalize_answer_reorder_sentence; print(normalize_answer_reorder_sentence('I eat apples') == normalize_answer_reorder_sentence('I eat apples.'))"
   ```

2. **Test Bug Reports Endpoint:**
   ```bash
   # Start server
   docker-compose up
   
   # Update API key in test script
   # Run test
   python test_bug_report.py
   ```

### Manual Testing

1. **Create diagnostic session** via `/v1/learning/diagnostic/start`
2. **Submit reorder_sentence answer** with no punctuation
3. **Verify it's marked correct** when expected answer has punctuation
4. **Submit bug report** via `/v1/feedback/bug-reports`
5. **Check database** for stored report:
   ```sql
   SELECT * FROM bug_reports ORDER BY created_at DESC LIMIT 5;
   ```

---

## Deployment Notes

### Database Migration

The new `bug_reports` table is created automatically on server start via the schema initialization in `db.py`. No manual migration needed.

### Backward Compatibility

- ✓ All existing diagnostic endpoints unchanged
- ✓ All existing task types unaffected
- ✓ Only `reorder_sentence` grading behavior improved
- ✓ New endpoint doesn't affect existing functionality

### Performance Impact

- **Normalization:** Minimal overhead (regex + unicode operations)
- **Bug Reports:** Simple INSERT operation
- **Indexes:** Created for efficient querying by user_id, created_at, kind

---

## Future Enhancements

### Grading
- Consider adding difficulty-based normalization (A1/A2 could be more lenient)
- Add fuzzy matching for typos in other task types
- Track normalization method used in attempts table

### Bug Reports
- Add admin endpoint to query/export bug reports
- Add analytics dashboard for bug report trends
- Implement automatic issue creation for high-severity reports
- Add report deduplication based on context similarity

---

## Security Considerations

- ✓ Authentication required (same as other /v1 endpoints)
- ✓ User context captured from auth (no spoofing)
- ✓ Rate limiting applied (standard pattern)
- ✓ Payload size limited (Pydantic validation)
- ✓ User message max length: 5000 chars
- ✓ No PII required in bug reports

---

## Monitoring & Logging

All operations include structured logging:

```python
logging.info(
    "[BUG_REPORT] Report received",
    extra={
        "report_id": "bug_abc123",
        "user_id": "user_123",
        "kind": "grading_mismatch",
        "severity": "major",
        "duration_ms": 15
    }
)
```

Logs can be queried via:
```bash
docker-compose logs api | grep "BUG_REPORT"
```

---

## Questions & Support

For questions or issues, contact the Seed Server team or file an issue in the repository.
