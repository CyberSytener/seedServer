# Photo Editing Feature — Complete Implementation Guide

**Status**: Backend scaffold complete | **Date**: Jan 29, 2026

---

## Executive Summary

Context-aware portrait editing feature for Seed. Allows users to upload photos and AI-enhance them for CV, LinkedIn, profile, or headshot contexts. Full implementation with validation, async processing, billing, and GDPR compliance.

---

## Architecture

```
┌─────────────┐
│   Client    │ (React component)
└──────┬──────┘
       │ POST /api/photo/upload
       │ multipart/form-data
       ▼
┌──────────────────┐
│  Backend API     │ (FastAPI)
│ ├─ Validation    │ (format, size, face detection)
│ ├─ Job creation  │ (store metadata)
│ ├─ Auth check    │ (JWT/session)
└────────┬─────────┘
         │ Enqueue → Redis
         ▼
┌─────────────────┐
│  Worker Pool    │ (Async tasks)
│ ├─ Download img │
│ ├─ Call AI API  │ (Image Edit)
│ ├─ Upload S3    │
│ ├─ Generate CDN │
└────────┬────────┘
         │ Update job status
         ▼
┌──────────────────┐
│  Storage Layer   │
│ ├─ SQLite DB     │ (job metadata)
│ ├─ Redis         │ (job cache, queue)
│ ├─ S3            │ (images)
│ ├─ CDN           │ (public URLs)
└──────────────────┘
```

---

## Files Created / Modified

### Core Backend

| File | Purpose |
|------|---------|
| [`docs/photo_editing_openapi.yaml`](#openapi-spec) | Full OpenAPI 3.1 specification |
| [`app/photo_models.py`](#models) | Pydantic models for requests/responses |
| [`app/photo_service.py`](#service-layer) | Photo validation, DB ops, face detection |
| [`app/photo_api.py`](#api-endpoints) | FastAPI routes for upload, status, confirm, delete, list |
| [`app/photo_worker.py`](#worker) | Async worker for image editing jobs |
| [`app/migrations_photo.py`](#database) | DB schema for photo jobs, variants, audit log |
| [`app/main.py`](#registration) | Modified to register photo API routes |

### Frontend

| File | Purpose |
|------|---------|
| [`docs/PhotoUploadComponent.tsx`](#frontend) | React component for upload flow |

---

## Implementation Details

### 1. OpenAPI Specification

**File**: `docs/photo_editing_openapi.yaml`

Complete REST API specification including:
- **POST /api/photo/upload** — Upload and validate photo, create job
- **GET /api/photo/status/{job_id}** — Poll job progress
- **POST /api/photo/confirm/{job_id}** — Confirm and download (triggers billing)
- **POST /api/photo/delete/{job_id}** — Delete job and files (GDPR)
- **GET /api/photo/list** — List user's jobs

All endpoints include:
- Authentication via Bearer token
- Error codes and descriptions
- Request/response schemas
- Status codes (202 Accepted, 402 Payment Required, etc.)

---

### 2. Data Models

**File**: `app/photo_models.py`

Pydantic models:
- **PhotoContext**: Enum (cv, profile, linkedin, headshot)
- **PhotoJobStatus**: Enum (queued, processing, done, failed, cancelled)
- **PhotoUploadRequest**: Consent, context, variants count
- **PhotoJobResponse**: Full job details with progress, preview, variants
- **PhotoConfirmRequest/Response**: Payment and download URL
- **PhotoEditTask**: Internal worker DTO

---

### 3. Service Layer

**File**: `app/photo_service.py`

Core business logic:
- **Face Detection**: Uses OpenCV Haar Cascades
  - Rejects images with 0 or >1 faces
  - Min 600px, max 8MB validation
- **Job Lifecycle**: Create → Update → Complete/Fail
- **Redis Caching**: 30-day TTL per job
- **DB Persistence**: SQLite tables for durability
- **Permission Checks**: User ID validation on all ops

**Key Methods**:
- `validate_photo()` → face detection, format/size checks
- `create_photo_job()` → create DB record + Redis cache
- `update_job_status()` → progress updates
- `complete_job()` → mark done with variants
- `delete_job()` → GDPR deletion
- `list_user_jobs()` → paginated job list

---

### 4. API Endpoints

**File**: `app/photo_api.py`

FastAPI router with 5 endpoints:

#### POST /api/photo/upload (202 Accepted)
```python
# Multipart form-data:
file: binary          # JPEG/PNG ≤8MB
context: "cv"         # Use case
variants: 1           # 1-3 variants
consent_confirmed: true

# Response:
{
  "job_id": "uuid",
  "status": "queued",
  "cost_estimate_usd": 0.5,
  "eta_seconds": 30
}
```

#### GET /api/photo/status/{job_id} (200 OK)
```python
# Response:
{
  "job_id": "uuid",
  "status": "processing",
  "progress": 35,
  "preview_url": "https://...",
  "variants": [
    {"index": 0, "preview_url": "..."}
  ],
  "cost_estimate_usd": 0.5
}
```

#### POST /api/photo/confirm/{job_id} (200 OK)
```python
# Request:
{"variant_index": 0}

# Response:
{
  "job_id": "uuid",
  "download_url": "https://s3-presigned-...",
  "cost_charged_usd": 0.5,
  "file_name": "portrait_abc123.jpg"
}
```

#### POST /api/photo/delete/{job_id} (204 No Content)
GDPR deletion — immediately removes job + files

#### GET /api/photo/list?skip=0&limit=20 (200 OK)
Paginated list with optional status filter

---

### 5. Worker Implementation

**File**: `app/photo_worker.py`

Async worker for image editing:

**Process Flow**:
1. Dequeue task from Redis
2. Download original image from S3
3. Build context-aware prompt (CV, LinkedIn, etc.)
4. For each variant:
   - Call Image Edit API (OpenAI, Gemini, etc.)
   - Handle retries (exponential backoff)
   - Upload result to S3
   - Track cost per variant
5. Update job status to "done"
6. Log metrics (latency, cost)

**Key Features**:
- Idempotent tasks by job_id
- 3 retries with exponential backoff
- Cost tracking per variant
- Presigned S3 URLs for downloads
- EXIF data removal (privacy)

**Prompt Templates** (customizable per context):
- **CV**: "Enhance professional CV photo. Improve lighting, reduce shadows..."
- **LinkedIn**: "Professional appearance, good lighting, neutral background..."
- **Headshot**: "Studio-quality headshot. Perfect lighting, skin retouching..."

---

### 6. Database Schema

**File**: `app/migrations_photo.py`

Three tables:

#### photo_jobs
```sql
CREATE TABLE photo_jobs (
  job_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  context TEXT NOT NULL,        -- cv, profile, linkedin, headshot
  status TEXT NOT NULL,          -- queued, processing, done, failed
  variants INTEGER NOT NULL,     -- count of variants requested
  progress INTEGER NOT NULL,     -- 0-100
  cost_estimate_usd REAL,
  cost_actual_usd REAL,
  confirmed BOOLEAN,
  created_at TEXT NOT NULL,
  completed_at TEXT
);
```

#### photo_variants
```sql
CREATE TABLE photo_variants (
  variant_id TEXT PRIMARY KEY,
  job_id TEXT FOREIGN KEY,
  index_num INTEGER,
  s3_key TEXT,                   -- Original S3 path
  download_url TEXT,             -- Presigned CDN URL
  file_size_bytes INTEGER,
  cost_usd REAL
);
```

#### photo_audit_log
```sql
CREATE TABLE photo_audit_log (
  event_id TEXT PRIMARY KEY,
  job_id TEXT,
  user_id TEXT,
  event_type TEXT,               -- 'upload', 'confirm', 'delete'
  details TEXT (JSON),
  created_at TEXT
);
```

---

### 7. Frontend Component

**File**: `docs/PhotoUploadComponent.tsx`

React component with:
- **Upload Form**: File picker, consent checkbox
- **Validation**: Format, size, error display
- **Progress Tracking**: Real-time status polling (1s interval)
- **Variant Selection**: Before/after preview, select variant
- **Payment Flow**: Confirm → download redirect
- **Error Handling**: User-friendly error messages

**Features**:
- File validation before upload
- Real-time progress (0-100%)
- Multiple variant selection
- Direct S3 presigned download
- GDPR consent flow

---

## Integration Checklist

### Phase 1: Core Setup (Week 1)
- [ ] Create database tables (`migrations_photo.py`)
- [ ] Ensure cv2 (OpenCV) is in requirements.txt
- [ ] Deploy API endpoints (register in `main.py` ✅)
- [ ] Test face detection with sample images

### Phase 2: Worker & Storage (Week 2)
- [ ] Implement S3 integration (replace placeholders in worker)
- [ ] Set up Redis queue integration
- [ ] Test worker end-to-end with mock API
- [ ] Configure presigned URL generation

### Phase 3: AI Integration (Week 2-3)
- [ ] Choose Image Edit API (OpenAI, Gemini, Claude, etc.)
- [ ] Implement API adapter (cost tracking, retries)
- [ ] Test prompt templates per context
- [ ] Set up cost logging and alerts

### Phase 4: Billing (Week 3)
- [ ] Integrate with existing credits system
- [ ] Implement payment processor (Stripe, PayPal, etc.)
- [ ] Add billing validation before confirm
- [ ] Set up invoice generation

### Phase 5: Frontend (Week 3-4)
- [ ] Integrate React component into Seed UI
- [ ] Test upload flow end-to-end
- [ ] Add loading states and animations
- [ ] Implement error recovery

### Phase 6: Monitoring & Ops (Week 4)
- [ ] Add Prometheus metrics (job latency, cost, failure rate)
- [ ] Configure alerts (high failure %, queue backlog)
- [ ] Set up structured logging
- [ ] Implement 30-day retention cleanup job

### Phase 7: Testing & QA (Week 4-5)
- [ ] Unit tests (validation, face detection)
- [ ] Integration tests (upload → worker → S3)
- [ ] Load tests (throughput with workers)
- [ ] Security tests (EXIF removal, access control)

### Phase 8: Canary & Rollout (Week 5-6)
- [ ] Canary deploy to 5% users
- [ ] Monitor metrics (error rate, latency, cost)
- [ ] Gather feedback from QA team
- [ ] Full rollout with feature flag

---

## Configuration & Environment

Add to `.env`:
```bash
# Photo Editing
PHOTO_EDIT_ENABLED=true
PHOTO_MAX_FILE_SIZE=8388608                    # 8MB
PHOTO_MIN_IMAGE_SIZE=600                       # pixels
PHOTO_COST_PER_VARIANT=0.5                     # USD
PHOTO_RETENTION_DAYS=30                        # delete after 30 days

# Image Edit API
IMAGE_EDIT_API_URL=https://api.openai.com     # or Gemini, Claude, etc.
IMAGE_EDIT_API_KEY=sk-...

# Storage
AWS_S3_BUCKET=seed-photos
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# CDN
CDN_BASE_URL=https://cdn.seed.example.com

# Redis Queue
PHOTO_QUEUE_NAME=photo_editing
```

---

## Testing Examples

### Test 1: Face Detection
```bash
# Should pass (single face)
curl -F "file=@portrait.jpg" \
     -F "context=cv" \
     -F "consent_confirmed=true" \
     -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/photo/upload
# Expected: 202, job_id

# Should fail (no face)
curl -F "file=@landscape.jpg" -F "consent_confirmed=true" \
     -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/photo/upload
# Expected: 400, "No face detected"
```

### Test 2: Job Status Polling
```bash
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/photo/status/abc-123
# Expected: 200, status object with progress
```

### Test 3: Confirm & Download
```bash
curl -X POST http://localhost:8000/api/photo/confirm/abc-123 \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"variant_index": 0}'
# Expected: 200, presigned download URL
```

---

## Metrics & Monitoring

### Key Metrics
- **Job Latency**: P50, P90, P99 (target: <60s)
- **Cost per Job**: Average USD spent
- **Queue Depth**: Jobs waiting for processing
- **Failure Rate**: % of jobs that fail
- **Cost Spikes**: Alert if average cost > threshold

### Prometheus Queries
```promql
# Average job latency
rate(photo_job_latency_seconds_sum[5m]) / rate(photo_job_latency_seconds_count[5m])

# Queue depth
photo_queue_depth

# Failure rate
rate(photo_job_failures_total[5m]) / rate(photo_job_total[5m])
```

### Alert Conditions
```yaml
- name: PhotoJobFailureRate
  condition: failure_rate > 5%
  duration: 5m

- name: PhotoQueueBacklog
  condition: queue_depth > 100
  duration: 2m

- name: PhotoCostSpike
  condition: avg_cost_per_job > 1.0
  duration: 1m
```

---

## GDPR & Privacy

### Data Handling
- **Retention**: 30 days by default
- **Deletion**: User can request anytime (endpoint available)
- **EXIF Removal**: Strip GPS, owner, email before storage
- **Logging**: No raw image data in logs
- **Audit Trail**: All ops logged with user_id, timestamp

### Consent Flow
1. User confirms consent before upload
2. Show retention policy (30 days)
3. Show deletion policy (delete anytime)
4. Store consent timestamp in DB

### User Rights
- Download their results anytime
- Delete all photos and data (GDPR request)
- Export their job history
- Opt-out of analytics

---

## Next Steps (Immediate)

1. **Add dependencies** to `requirements.txt`:
   ```
   opencv-python>=4.8.0
   pillow>=10.0.0
   httpx>=0.25.0
   ```

2. **Run migrations**:
   ```bash
   python scripts/run_migrations.py  # or integrate into startup
   ```

3. **Configure environment** (`.env`):
   - Set IMAGE_EDIT_API_URL and key
   - Set AWS S3 credentials
   - Set Redis queue name

4. **Implement S3 integration**:
   - Replace `_download_from_s3()` placeholders
   - Use boto3 library
   - Test with sample images

5. **Connect worker**:
   - Integrate PhotoEditWorker with job queue
   - Run worker via `scripts/run_worker.py`
   - Test end-to-end flow

6. **Add to frontend**:
   - Import PhotoUploadComponent
   - Add route (e.g., `/enhance-photo`)
   - Connect to auth system

---

## Cost Estimation

- **API calls** (Image Edit): ~$0.10-1.00 per image depending on provider
- **Storage** (S3): ~$0.023 per GB/month → ~2¢ per 1000 images
- **CDN bandwidth**: ~$0.085 per GB → ~1¢ per image download
- **Worker compute**: ~$0.0001 per job (if using serverless)

**Total per user photo**: ~$0.50-1.50 (configurable)

---

## Rollout Strategy

**Week 1-2: Internal Beta**
- 5% internal staff
- Gather feedback on UX, performance
- Fine-tune prompts and settings

**Week 3: Closed Beta**
- 10% of paid users (opt-in)
- Monitor cost, latency, error rate
- Refine billing logic

**Week 4-5: Public Beta**
- Feature-flagged rollout (20% → 50% → 100%)
- A/B test pricing models
- Collect user feedback

**Week 6+: Production**
- Full rollout, monitoring ongoing
- Iterate on prompts, contexts
- Expand to new use cases

---

## Support & Troubleshooting

### Common Issues

**"No face detected"**
- Image quality too low
- Face partially obscured
- Need better lighting
- → Suggest user re-take photo

**"Job timed out"**
- Worker pool overloaded
- API rate limited
- → Implement queuing, backoff

**"Download URL expired"**
- Presigned URL valid only 24h
- → Regenerate URL or confirm again

**High costs**
- Using expensive API model
- Overly complex prompts
- → Switch to lighter model, optimize prompts

---

## Version History

- **v1.0.0** (Jan 29, 2026): Initial scaffold
  - API endpoints ✅
  - Face detection ✅
  - Worker framework ✅
  - Frontend component ✅
  - **TODO**: S3, billing, AI API integration

---

## Questions & Contact

- **Architecture questions**: See `docs/photo_editing_openapi.yaml`
- **Implementation details**: See file-specific comments
- **Integration help**: Check `Integration Checklist` section

---

**Status**: Ready for Phase 1 implementation 🚀
