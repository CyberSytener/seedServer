"""
Photo editing API endpoints
FastAPI routes for photo upload, status, confirm, delete, and list
"""
from __future__ import annotations

import logging
import os

# File-size returned when real metadata is not available (storage service stub).
# Replace with actual metadata lookup once S3/GCS integration is wired up.
_PLACEHOLDER_FILE_SIZE_BYTES = 512_000

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from app.core.auth import verify_user_context
from app.models.photo import (
    PhotoConfirmRequest,
    PhotoConfirmResponse,
    PhotoContext,
    PhotoJobCreatedResponse,
    PhotoJobResponse,
    PhotoListResponse,
    PhotoUploadRequest,
)
from app.services.photo.service import PhotoService, PhotoValidationError
from app.services.photo.storage import PhotoStorageService
from app.infrastructure.redis.redisutil import RedisUtil
from app.services.photo.settings import PhotoEditingSettings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/photo", tags=["photo_editing"])
settings = PhotoEditingSettings()


def get_photo_service(redis: RedisUtil = Depends(lambda: RedisUtil())) -> PhotoService:
    """Dependency: get PhotoService instance"""
    service = PhotoService(redis)
    if service.face_cascade is None:
        raise HTTPException(status_code=503, detail="Photo validation dependencies not available")
    return service


def get_storage_service() -> PhotoStorageService:
    """Dependency: get PhotoStorageService instance"""
    try:
        return PhotoStorageService(
            bucket_name=settings.AWS_S3_BUCKET,
            region=settings.AWS_REGION,
            cdn_url=settings.CDN_BASE_URL,
            aws_access_key=settings.AWS_ACCESS_KEY_ID,
            aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/upload", response_model=PhotoJobCreatedResponse, status_code=202)
async def upload_photo(
    file: UploadFile = File(...),
    context: str = Form(default="cv"),
    variants: int = Form(default=1),
    consent_confirmed: bool = Form(default=False),
    authorization: str = Header(None),
    photo_service: PhotoService = Depends(get_photo_service),
    storage_service: PhotoStorageService = Depends(get_storage_service),
):
    """
    Upload and initiate photo editing job.
    Validates format, size, and face detection.
    Returns job_id for polling.
    """
    # Verify authentication
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]

    # Validate consent
    if not consent_confirmed:
        raise HTTPException(
            status_code=400,
            detail="User must confirm data retention and deletion policy",
        )

    # Parse context
    try:
        ctx = PhotoContext(context)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid context. Use: {', '.join([c.value for c in PhotoContext])}",
        )

    # Validate variants
    if not (1 <= variants <= settings.PHOTO_VARIANTS_MAX):
        raise HTTPException(
            status_code=400,
            detail=f"Variants must be 1-{settings.PHOTO_VARIANTS_MAX}"
        )

    # Read file
    try:
        file_bytes = await file.read()
    except Exception as e:
        logger.exception(f"Failed to read uploaded file for user {user_id}")
        raise HTTPException(status_code=400, detail="Failed to read file")

    # Validate photo
    validation_result = photo_service.validate_photo(file_bytes)
    if not validation_result["valid"]:
        error = validation_result["error"]
        logger.warning(f"Photo validation failed for user {user_id}: {error}")
        
        # Map to specific error codes
        if "No face" in error:
            code = "NO_FACE_DETECTED"
        elif "Multiple faces" in error:
            code = "MULTIPLE_FACES_DETECTED"
        elif "too large" in error:
            code = "FILE_TOO_LARGE"
        elif "too small" in error:
            code = "IMAGE_TOO_SMALL"
        else:
            code = "INVALID_FORMAT"

        raise HTTPException(
            status_code=400,
            detail={"error": error, "code": code},
        )

    # Estimate cost
    cost_estimate = settings.PHOTO_COST_PER_VARIANT * variants

    # Create job
    job_id = photo_service.create_photo_job(
        user_id=user_id,
        context=ctx,
        variants=variants,
        cost_estimate_usd=cost_estimate,
    )

    # Save original to S3
    try:
        await storage_service.upload_photo(
            file_bytes,
            job_id,
            user_id,
            is_original=True
        )
        logger.info(f"Saved original photo to S3 for job {job_id}")
    except Exception as e:
        logger.exception(f"Failed to save original to S3: {str(e)}")
        photo_service.fail_job(job_id, f"Failed to save photo: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to save photo")

    # Job is persisted; the background worker picks it up via Redis queue.
    # Worker integration is handled by the PhotoService.enqueue() layer.
    logger.info(f"Created photo job {job_id} for user {user_id}")

    return PhotoJobCreatedResponse(
        job_id=job_id,
        status="queued",
        queue_position=None,
        cost_estimate_usd=cost_estimate,
        eta_seconds=30,
    )


@router.get("/status/{job_id}", response_model=PhotoJobResponse)
async def get_job_status(
    job_id: str,
    authorization: str = Header(None),
    photo_service: PhotoService = Depends(get_photo_service),
):
    """Get photo editing job status, preview, and cost."""
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]

    job_data = photo_service.get_photo_job(job_id, user_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    # Convert to response model
    return PhotoJobResponse(
        job_id=job_data["job_id"],
        user_id=job_data["user_id"],
        context=PhotoContext(job_data["context"]),
        status=job_data["status"],
        progress=job_data.get("progress", 0),
        message=job_data.get("message"),
        preview_url=job_data.get("preview_url"),
        confirmed=job_data.get("confirmed", False),
        cost_estimate_usd=job_data.get("cost_estimate_usd"),
        cost_actual_usd=job_data.get("cost_actual_usd"),
        created_at=job_data["created_at"],
        completed_at=job_data.get("completed_at"),
    )


@router.post("/confirm/{job_id}", response_model=PhotoConfirmResponse)
async def confirm_photo(
    job_id: str,
    request: PhotoConfirmRequest = None,
    authorization: str = Header(None),
    photo_service: PhotoService = Depends(get_photo_service),
    storage_service: PhotoStorageService = Depends(get_storage_service),
):
    """
    Confirm and process payment for edited photo.
    After confirmation, download is available without watermark.
    """
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]

    if not request:
        request = PhotoConfirmRequest()

    job_data = photo_service.get_photo_job(job_id, user_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") != "done":
        raise HTTPException(
            status_code=400,
            detail="Job not completed yet. Wait for processing to finish.",
        )

    if job_data.get("confirmed"):
        raise HTTPException(status_code=400, detail="Job already confirmed")

    # Billing is intentionally deferred in this build.
    # The endpoint confirms the job and records the cost for audit purposes;
    # payment processing (credits / Stripe) would be inserted here in production.

    cost_actual = job_data.get("cost_actual_usd", 0.0)

    # Mark as confirmed
    photo_service.confirm_job(job_id, user_id, request.variant_index, cost_actual)

    # Generate presigned download URL (24 hours)
    variants_data = job_data.get("variants_data", [])
    if request.variant_index < len(variants_data):
        s3_key = variants_data[request.variant_index].get("s3_key")
        download_url = storage_service.generate_presigned_url(
            s3_key,
            expiration_hours=settings.CDN_PRESIGNED_URL_EXPIRY_HOURS,
            filename=f"portrait_{job_id[:8]}.jpg"
        )
    else:
        download_url = f"https://cdn.seed.example.com/photo-results/{job_id}/variant_{request.variant_index}.jpg"

    return PhotoConfirmResponse(
        job_id=job_id,
        confirmed_at=job_data["created_at"],
        cost_charged_usd=cost_actual,
        download_url=download_url,
        file_size_bytes=_PLACEHOLDER_FILE_SIZE_BYTES,
        file_name=f"portrait_{job_id[:8]}.jpg",
    )


@router.post("/delete/{job_id}")
async def delete_photo(
    job_id: str,
    authorization: str = Header(None),
    photo_service: PhotoService = Depends(get_photo_service),
    storage_service: PhotoStorageService = Depends(get_storage_service),
):
    """Delete job and files (GDPR compliance)."""
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]

    success = photo_service.delete_job(job_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found")

    # Delete from S3
    try:
        await storage_service.delete_photo(
            f"uploads/{user_id}/{job_id}",
            also_variants=True
        )
        logger.info(f"Deleted photo files for job {job_id}")
    except Exception as e:
        logger.warning(f"Failed to delete S3 files: {str(e)}")

    logger.info(f"Photo job {job_id} deleted by user {user_id} (GDPR)")
    return JSONResponse(status_code=204, content={})


@router.get("/list", response_model=PhotoListResponse)
async def list_photos(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    authorization: str = Header(None),
    photo_service: PhotoService = Depends(get_photo_service),
):
    """List user's photo editing jobs."""
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]

    result = photo_service.list_user_jobs(user_id, skip=skip, limit=limit, status=status)
    return PhotoListResponse(
        total=result["total"],
        jobs=[PhotoJobResponse(**job) for job in result["jobs"]],
    )


# ===== PHASE 4: BILLING & CREDITS ENDPOINTS =====


@router.get("/billing/credits")
async def get_user_credits(
    authorization: str = Header(None),
):
    """Get current user credit balance."""
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]
    
    try:
        from app.billing_service import PhotoBillingService
        from app.services.photo.integration import get_seed_db_session
        
        db_session = get_seed_db_session()
        billing_service = PhotoBillingService(db_session)
        
        balance = await billing_service.check_user_credits(user_id)
        balance_usd = billing_service.credits_to_usd(balance)
        
        return JSONResponse({
            "user_id": user_id,
            "credits": balance,
            "balance_usd": balance_usd,
        })
    except Exception as e:
        logger.error(f"Failed to get credits: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing/transactions")
async def get_credit_history(
    limit: int = Query(50, ge=1, le=200),
    authorization: str = Header(None),
):
    """Get user's credit transaction history."""
    user_context = verify_user_context(authorization)
    if not user_context:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_context["user_id"]
    
    try:
        from app.billing_service import PhotoBillingService
        from app.services.photo.integration import get_seed_db_session
        
        db_session = get_seed_db_session()
        billing_service = PhotoBillingService(db_session)
        
        transactions = billing_service.get_user_transaction_history(user_id, limit=limit)
        
        return JSONResponse({
            "user_id": user_id,
            "transactions": transactions,
        })
    except Exception as e:
        logger.error(f"Failed to get transaction history: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))



