# Photo Editing Feature — Quick Start Guide

**Status**: Implementation scaffolds ready | **Estimated setup time**: 2-3 hours

---

## What Was Built

Complete backend scaffold for portrait photo editing with:
- ✅ 5 REST API endpoints (upload, status, confirm, delete, list)
- ✅ Face detection (OpenCV Haar Cascade)
- ✅ Async worker framework
- ✅ Database schema (3 tables)
- ✅ React frontend component
- ✅ S3/CDN storage integration
- ✅ OpenAPI specification
- ✅ Full documentation

---

## Files Created

```
docs/
├── photo_editing_openapi.yaml          OpenAPI 3.1 spec
├── PHOTO_EDITING_IMPLEMENTATION.md     Full guide (this doc)
├── PhotoUploadComponent.tsx            React component
└── photo_editing_quick_start.md        This file

app/
├── photo_models.py                     Pydantic models
├── photo_api.py                        FastAPI endpoints
├── photo_service.py                    Core business logic
├── photo_worker.py                     Async worker
├── photo_storage.py                    S3/CDN integration
├── photo_integration.py                Queue system integration
├── migrations_photo.py                 DB schema
└── main.py                             (modified: added router)
```

---

## Step-by-Step Setup

### 1. Install Dependencies (5 min)

```bash
# Add to requirements.txt:
opencv-python>=4.8.0
pillow>=10.0.0
piexif>=1.1.3
boto3>=1.28.0
httpx>=0.25.0

# Install
pip install -r requirements.txt
```

### 2. Configure Environment (5 min)

Add to `.env`:
```bash
# Photo Editing
PHOTO_EDIT_ENABLED=true
PHOTO_MAX_FILE_SIZE=8388608
PHOTO_MIN_IMAGE_SIZE=600
PHOTO_RETENTION_DAYS=30

# Image Edit API (choose one)
IMAGE_EDIT_API_URL=https://api.openai.com
IMAGE_EDIT_API_KEY=sk-...

# Or for Gemini:
IMAGE_EDIT_API_URL=https://generativelanguage.googleapis.com
IMAGE_EDIT_API_KEY=AIzaSy...

# AWS S3
AWS_S3_BUCKET=seed-photos
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...

# CDN
CDN_BASE_URL=https://cdn.seed.example.com
```

### 3. Initialize Database (5 min)

```bash
# Option A: Automatic (on app startup)
# Migrations run automatically if enabled in settings

# Option B: Manual
python -c "
from app.db import get_db
from app.migrations_photo import migrate
db = get_db()
migrate(db)
print('✓ Photo tables created')
"
```

### 4. Test API Endpoints (10 min)

#### Test 1: Check API is running
```bash
curl http://localhost:8000/api/photo/list \
  -H "Authorization: Bearer YOUR_TOKEN"
# Expected: {"total": 0, "jobs": []}
```

#### Test 2: Upload photo
```bash
# Get a test image
curl -o test.jpg https://picsum.photos/800

# Upload
curl -F "file=@test.jpg" \
     -F "context=cv" \
     -F "variants=2" \
     -F "consent_confirmed=true" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Accept: application/json" \
     http://localhost:8000/api/photo/upload

# Expected response:
# {"job_id": "abc-123", "status": "queued", "cost_estimate_usd": 0.5, "eta_seconds": 30}
```

#### Test 3: Check job status
```bash
JOB_ID="abc-123"  # From upload response

curl http://localhost:8000/api/photo/status/$JOB_ID \
  -H "Authorization: Bearer YOUR_TOKEN"

# Expected (queued):
# {"job_id": "abc-123", "status": "queued", "progress": 0, ...}

# After worker processes:
# {"job_id": "abc-123", "status": "done", "progress": 100, "variants": [...], ...}
```

### 5. Start Worker (10 min)

Option A: Use existing worker pool
```bash
# Add photo queue to existing worker
python scripts/run_worker.py --queue photo_editing --name photo_worker
```

Option B: Create dedicated worker
```bash
# Create scripts/run_photo_worker.py
cat > scripts/run_photo_worker.py << 'EOF'
#!/usr/bin/env python
import asyncio
import sys
sys.path.insert(0, '.')

from app.photo_integration import PhotoEditingQueueIntegration
from app.queue_redis import QueueManager
from app.redisutil import RedisUtil

async def main():
    redis = RedisUtil()
    queue_mgr = QueueManager(redis)
    integration = PhotoEditingQueueIntegration()
    
    print("Starting photo worker...")
    while True:
        task = queue_mgr.dequeue("photo_editing")
        if task:
            print(f"Processing task: {task['job_id']}")
            success = await integration.process_photo_task(task)
            if success:
                queue_mgr.acknowledge(task)
        else:
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
EOF

python scripts/run_photo_worker.py
```

### 6. Test End-to-End (20 min)

```bash
#!/bin/bash
set -e

# Step 1: Upload
echo "📤 Uploading photo..."
RESPONSE=$(curl -s -F "file=@test.jpg" \
                    -F "context=cv" \
                    -F "variants=1" \
                    -F "consent_confirmed=true" \
                    -H "Authorization: Bearer $TOKEN" \
                    http://localhost:8000/api/photo/upload)

JOB_ID=$(echo $RESPONSE | jq -r '.job_id')
echo "✓ Job created: $JOB_ID"

# Step 2: Wait for processing
echo "⏳ Waiting for processing (max 2 min)..."
for i in {1..120}; do
    STATUS=$(curl -s http://localhost:8000/api/photo/status/$JOB_ID \
                      -H "Authorization: Bearer $TOKEN")
    
    STATUS_VALUE=$(echo $STATUS | jq -r '.status')
    PROGRESS=$(echo $STATUS | jq -r '.progress')
    
    echo "  Progress: $PROGRESS%, Status: $STATUS_VALUE"
    
    if [ "$STATUS_VALUE" == "done" ]; then
        echo "✓ Processing complete!"
        PREVIEW=$(echo $STATUS | jq -r '.preview_url')
        echo "  Preview: $PREVIEW"
        break
    elif [ "$STATUS_VALUE" == "failed" ]; then
        echo "✗ Processing failed!"
        echo $STATUS | jq '.'
        exit 1
    fi
    
    sleep 1
done

# Step 3: Confirm and download
echo "💳 Confirming download..."
CONFIRM=$(curl -s -X POST http://localhost:8000/api/photo/confirm/$JOB_ID \
                           -H "Authorization: Bearer $TOKEN" \
                           -H "Content-Type: application/json" \
                           -d '{"variant_index": 0}')

DOWNLOAD_URL=$(echo $CONFIRM | jq -r '.download_url')
COST=$(echo $CONFIRM | jq -r '.cost_charged_usd')

echo "✓ Download URL: $DOWNLOAD_URL"
echo "✓ Cost charged: \$$COST"

# Step 4: Download result
echo "⬇️  Downloading..."
curl -o result.jpg "$DOWNLOAD_URL"
echo "✓ Saved to result.jpg"
```

### 7. Integrate into Frontend (15 min)

In your React app:

```typescript
// pages/EnhancePhoto.tsx
import PhotoUploadComponent from '@/components/PhotoUploadComponent';

export function EnhancePhotoPage() {
  return (
    <div className="page">
      <h1>Enhance Your Portrait</h1>
      <PhotoUploadComponent
        context="cv"
        onSuccess={(jobId) => {
          console.log('Job started:', jobId);
          // Track analytics, show success toast, etc.
        }}
        onError={(error) => {
          console.error('Upload failed:', error);
          // Show error notification
        }}
      />
    </div>
  );
}
```

---

## Next: Choose Your AI Provider

### Option 1: OpenAI (Recommended for production)

```bash
# Install
pip install openai

# .env
IMAGE_EDIT_API_KEY=sk-...

# Usage (in photo_worker.py):
import openai
response = await openai.Image.acreate(
    image=open(image_path, "rb"),
    prompt="Enhance professional CV photo...",
    n=1,
    size="1024x1024",
)
```

### Option 2: Google Gemini

```bash
# Install
pip install google-generativeai

# .env
IMAGE_EDIT_API_KEY=AIzaSy...

# Usage:
import google.generativeai as genai
genai.configure(api_key=os.getenv('IMAGE_EDIT_API_KEY'))
response = await genai.GenerativeModel('gemini-pro-vision').generate_content([
    "Enhance professional CV photo",
    image_file
])
```

### Option 3: Anthropic Claude

```bash
# Install
pip install anthropic

# .env
IMAGE_EDIT_API_KEY=sk-ant-...

# Usage:
import anthropic
client = anthropic.Anthropic(api_key=os.getenv('IMAGE_EDIT_API_KEY'))
response = await client.messages.create(
    model="claude-3-vision-20240229",
    messages=[...]
)
```

---

## Testing Checklist

- [ ] API endpoints accessible
- [ ] Face detection rejects multi-face images
- [ ] Photo upload validates format/size
- [ ] Worker picks up tasks
- [ ] S3 upload/download works
- [ ] Presigned URLs generated correctly
- [ ] EXIF data removed from results
- [ ] Cost tracking logged
- [ ] Job status polling works
- [ ] End-to-end flow completes

---

## Production Deployment

### Step 1: Docker Setup
```dockerfile
# Add to Dockerfile:
RUN pip install -r requirements_photo.txt

# Add OpenCV system dependencies:
RUN apt-get update && apt-get install -y libsm6 libxext6
```

### Step 2: Docker Compose
```yaml
# Add to docker-compose.yml:
worker_photo:
  build: .
  command: ["python", "scripts/run_worker.py", "--queue", "photo_editing"]
  environment:
    - IMAGE_EDIT_API_KEY=${IMAGE_EDIT_API_KEY}
    - AWS_S3_BUCKET=${AWS_S3_BUCKET}
  depends_on:
    - redis
    - api
```

### Step 3: Monitoring
```bash
# Check worker health
curl http://localhost:8000/metrics | grep photo_

# Watch logs
docker logs -f seed_server-worker_photo-1
```

### Step 4: Load Testing
```bash
# Simple load test
ab -n 100 -c 10 -H "Authorization: Bearer $TOKEN" \
   http://localhost:8000/api/photo/list
```

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No face detected" | Check image quality, lighting, ensure single face |
| "File too large" | Max 8MB; compress or resize image |
| "Worker not picking up tasks" | Check Redis connection, queue name |
| "S3 upload fails" | Verify AWS credentials, bucket exists, region correct |
| "High latency" | Add more workers, check API rate limits |
| "Presigned URL expired" | Valid only 24h; regenerate or confirm again |

---

## Performance Targets

- **Upload to queue**: < 100ms
- **Face detection**: < 500ms
- **API call**: 10-30s (depends on provider)
- **Full job**: 20-60s
- **Queue depth**: < 100 jobs at p95

---

## Cost Estimation

Per photo enhancement:
- **API call** (OpenAI): ~$0.10
- **S3 storage**: ~$0.001 (30 days)
- **Bandwidth**: ~$0.001
- **Compute**: ~$0.01 (server)
- **Total**: ~$0.11-0.20 per photo

Recommended pricing: **$0.99 per enhancement**

---

## Support & Questions

### Common Questions

**Q: Can I use multiple AI providers?**
A: Yes! Modify `photo_worker.py` to switch providers based on context or load.

**Q: How do I handle high volume?**
A: Horizontal scaling: run multiple worker instances pointing to same Redis queue.

**Q: Can I add custom editing styles?**
A: Yes! Add new PhotoContext enum values and matching prompt templates.

**Q: GDPR deletion?**
A: Endpoint `/api/photo/delete/{job_id}` removes all data. Auto-cleanup after 30 days.

---

## Next Steps

1. **Week 1**: Complete S3 integration + test with sample images
2. **Week 2**: Deploy worker + test end-to-end
3. **Week 3**: Integrate AI API + set up billing
4. **Week 4**: Ship to internal beta
5. **Week 5**: Public rollout

---

**Ready to start? Begin with Step 1: Install Dependencies** ⬆️

Questions? See `PHOTO_EDITING_IMPLEMENTATION.md` for full documentation.
