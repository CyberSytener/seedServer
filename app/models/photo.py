"""
Photo editing models and schemas
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class PhotoContext(str, Enum):
    """Use case context for photo editing"""
    cv = "cv"
    profile = "profile"
    linkedin = "linkedin"
    headshot = "headshot"


class PhotoJobStatus(str, Enum):
    """Status of photo editing job"""
    queued = "queued"
    face_detection = "face_detection"
    processing = "processing"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class PhotoUploadRequest(BaseModel):
    """Request schema for photo upload"""
    model_config = {"populate_by_name": True}
    
    context: PhotoContext = PhotoContext.cv
    variants: int = Field(default=1, ge=1, le=3)
    consent_confirmed: bool = Field(
        default=False,
        description="User confirmed data retention and deletion policy"
    )


class PhotoVariant(BaseModel):
    """Single variant of edited photo"""
    index: int
    preview_url: Optional[str] = None
    download_url: Optional[str] = None
    s3_key: Optional[str] = None
    file_size_bytes: Optional[int] = None


class PhotoJobResponse(BaseModel):
    """Photo editing job details"""
    model_config = {"populate_by_name": True}
    
    job_id: str
    user_id: str
    context: PhotoContext
    status: PhotoJobStatus
    progress: int = Field(default=0, ge=0, le=100)
    message: Optional[str] = None
    preview_url: Optional[str] = None
    variants: list[PhotoVariant] = Field(default_factory=list)
    confirmed: bool = False
    cost_estimate_usd: Optional[float] = None
    cost_actual_usd: Optional[float] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class PhotoJobCreatedResponse(BaseModel):
    """Response after job creation"""
    job_id: str
    status: PhotoJobStatus
    queue_position: Optional[int] = None
    cost_estimate_usd: Optional[float] = None
    eta_seconds: Optional[int] = None


class PhotoConfirmRequest(BaseModel):
    """Request to confirm and download photo"""
    variant_index: int = Field(default=0, ge=0, le=2)


class PhotoConfirmResponse(BaseModel):
    """Response after confirmation and payment"""
    job_id: str
    confirmed_at: datetime
    cost_charged_usd: float
    download_url: str
    file_size_bytes: int
    file_name: str


class PhotoListResponse(BaseModel):
    """List of user's photo jobs"""
    total: int
    jobs: list[PhotoJobResponse]


# Internal DTO for worker
class PhotoEditTask(BaseModel):
    """Worker task for photo editing"""
    job_id: str
    user_id: str
    context: PhotoContext
    variants: int
    original_s3_key: str
    cost_estimate_usd: float
    prompt_template: Optional[str] = None
    created_at: datetime
