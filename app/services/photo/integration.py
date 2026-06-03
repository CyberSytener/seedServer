"""
Integration example: How to connect photo editing worker to Seed's job queue system

This shows how to:
1. Enqueue photo editing tasks to Redis
2. Register worker pool to process them
3. Integrate with existing metrics and monitoring
"""

import logging
import os
from datetime import datetime, timezone

from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.redisutil import RedisPool, RedisUtil
from app.services.photo.worker import PhotoEditWorker
from app.services.photo.service import PhotoService
from app.services.photo.storage import PhotoStorageService
from app.settings import get_settings

logger = logging.getLogger(__name__)


class PhotoEditingQueueIntegration:
    """Bridge between photo API and job queue system"""

    def __init__(self):
        self.settings = get_settings()
        self.redis = RedisUtil()
        self.redis_pool = RedisPool(self.settings.redis_url)
        self.queue_mgr = RedisQueueHub(
          r=self.redis_pool.client(),
          namespace=self.settings.redis_namespace,
        )
        self.photo_service = PhotoService(self.redis)
        
        # Initialize S3 storage service
        self.storage_service = PhotoStorageService(
            bucket_name=os.getenv("AWS_S3_BUCKET", "seed-photos"),
            region=os.getenv("AWS_REGION", "us-east-1"),
            cdn_url=os.getenv("CDN_BASE_URL", "https://cdn.seed.example.com"),
            aws_access_key=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        
        # Initialize billing service (Phase 4)
        from app.billing_service import PhotoBillingService
        self.db_session = get_seed_db_session()
        self.billing_service = PhotoBillingService(self.db_session)
        
        # Initialize worker with all dependencies
        self.worker = PhotoEditWorker(
            redis=self.redis,
            photo_service=self.photo_service,
            storage_service=self.storage_service,
            image_edit_api_url=self.settings.image_edit_api_url,
            image_edit_api_key=self.settings.image_edit_api_key,
            billing_service=self.billing_service,
        )

    async def enqueue_photo_job(self, job_id: str, user_id: str, context: str, variants: int) -> None:
        """
        Called after photo upload validation succeeds.
        Adds task to Redis queue for worker to pick up.
        
        Usage:
            # In photo_api.py upload endpoint, after creating job:
            integration.enqueue_photo_job(job_id, user_id, context, variants)
        """
        task = {
            "type": "photo_edit",
            "job_id": job_id,
            "user_id": user_id,
            "context": context,
            "variants": variants,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self.redis.set_dict(
          f"photo_job:{job_id}",
          task,
          ttl_seconds=30 * 24 * 60 * 60,
        )

        # Add to Redis queue
        queue_name = "photo_editing"
        priority = 10  # Normal priority

        await self.queue_mgr.enqueue(
          queue_name=queue_name,
          job_id=job_id,
          priority=priority,
        )

        logger.info(f"Enqueued photo job {job_id} to {queue_name}")

    async def process_photo_task(self, job_id: str) -> bool:
        """
        Worker callback. Called by existing Seed worker pool.
        
        Usage (in scripts/run_worker.py):
            integration = PhotoEditingQueueIntegration()
            
            while True:
                task = queue_mgr.dequeue("photo_editing")
                if task:
                    success = asyncio.run(integration.process_photo_task(task))
                    if success:
                        queue_mgr.acknowledge(task)
        """
        logger.info(f"Processing photo task: {job_id}")
        
        try:
            success = await self.worker.process_job(job_id)
            return success
        except Exception as e:
            logger.exception(f"Photo task failed: {str(e)}")
            self.photo_service.fail_job(job_id, str(e))
            return False


# Example: How to modify existing run_worker.py to support photo tasks
"""
# In scripts/run_worker.py, add this:

import sys
import asyncio
from app.services.photo.integration import PhotoEditingQueueIntegration

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", default="q_fast")
    parser.add_argument("--name", default="worker")
    args = parser.parse_args()
    
    queue_mgr = RedisQueueHub(r=redis_pool.client(), namespace=settings.redis_namespace)
    
    # Support multiple queue types
    if args.queue == "photo_editing":
        photo_integration = PhotoEditingQueueIntegration()
        
        while True:
            job_id = await queue_mgr.dequeue("photo_editing")
            if job_id:
              await photo_integration.process_photo_task(job_id)
            else:
                await asyncio.sleep(1)
    else:
        # Existing worker logic for other queues
        while True:
            job_id = await queue_mgr.dequeue(args.queue)
            if job_id:
              # Process existing task types...
              pass
"""


# Example: Modified photo_api.py upload endpoint
"""
# In app/photo_api.py, modify the upload endpoint:

from datetime import datetime

@router.post("/upload", response_model=PhotoJobCreatedResponse, status_code=202)
async def upload_photo(...):
    # ... existing validation code ...
    
    # Create job
    job_id = photo_service.create_photo_job(...)
    
    # CHANGED: Enqueue to worker pool
    integration = PhotoEditingQueueIntegration()
    await integration.enqueue_photo_job(job_id, user_id, ctx.value, variants)
    
    return PhotoJobCreatedResponse(
        job_id=job_id,
        status="queued",
        cost_estimate_usd=cost_estimate,
        eta_seconds=30,
    )
"""


# Example: docker-compose configuration
"""
# Update docker-compose.yml to add photo worker service:

  worker_photo:
    build: .
    command: ["python", "scripts/run_worker.py", "--queue", "photo_editing", "--name", "photo"]
    env_file:
      - .env
    environment:
      - SEED_REDIS_URL=${SEED_REDIS_URL:-redis://redis:6379/0}
      - IMAGE_EDIT_API_URL=${IMAGE_EDIT_API_URL:-https://api.openai.com}
      - IMAGE_EDIT_API_KEY=${IMAGE_EDIT_API_KEY}
      - AWS_S3_BUCKET=${AWS_S3_BUCKET}
    volumes:
      - seed_data:/data
    depends_on:
      - redis
      - api
    restart: unless-stopped
"""


# Example: Metrics integration
"""
# In app/metrics.py or app/monitoring, add:

from prometheus_client import Counter, Histogram

PHOTO_JOBS_CREATED = Counter(
    'photo_jobs_created_total',
    'Total photo editing jobs created',
    ['context', 'user_type']
)

PHOTO_JOB_LATENCY = Histogram(
    'photo_job_latency_seconds',
    'Photo job processing latency',
    ['context', 'status']
)

PHOTO_COST_USD = Counter(
    'photo_cost_usd_total',
    'Total cost spent on photo editing',
    ['context']
)

# Usage in worker:
PHOTO_JOBS_CREATED.labels(context=context, user_type="free").inc()
PHOTO_JOB_LATENCY.labels(context=context, status="done").observe(latency_seconds)
PHOTO_COST_USD.labels(context=context).inc(cost_actual)
"""


# Example: Alerting rules (Prometheus)
"""
groups:
  - name: photo_editing
    rules:
      - alert: PhotoJobFailureRate
        expr: |
          (rate(photo_job_failures_total[5m]) / 
           rate(photo_jobs_total[5m])) > 0.05
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Photo job failure rate > 5%"

      - alert: PhotoQueueBacklog
        expr: photo_queue_depth > 100
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Photo queue backlog > 100 jobs"

      - alert: PhotoCostSpike
        expr: rate(photo_cost_usd_total[1h]) > 100
        for: 1m
        labels:
          severity: warning
        annotations:
          summary: "Photo editing cost spike detected"
"""


if __name__ == "__main__":
    # Test the integration
    import asyncio
    
    integration = PhotoEditingQueueIntegration()
    
    # Example task
    test_task = {
        "type": "photo_edit",
        "job_id": "test-job-123",
        "user_id": "user-456",
        "context": "cv",
        "variants": 2,
    }
    
    # This would be called by worker loop
    # success = asyncio.run(integration.process_photo_task(test_task))
    # print(f"Task processed: {success}")


# ===== PHASE 4: HELPER FUNCTIONS =====

def get_seed_db_session():
    """Get SQLAlchemy session from Seed's database"""
    from app.infrastructure.db.sqlite import SessionLocal  # Assuming Seed provides this
    return SessionLocal()


def get_seed_user_service():
    """Get user service from Seed"""
    from app.user_service import UserService  # Assuming Seed provides this
    return UserService()


