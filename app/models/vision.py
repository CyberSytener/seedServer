"""
Vision intake and storage models
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class VisionBaseModel(BaseModel):
    model_config = {"protected_namespaces": ()}


class VisionAnalysis(VisionBaseModel):
    product_name: str
    quantity: float
    unit: str
    expires_at: Optional[str] = None
    sku: Optional[str] = None
    barcode: Optional[str] = None
    confidence: Optional[float] = None
    notes: Optional[str] = None


class VisionIntakeRecord(VisionBaseModel):
    intake_id: str
    user_id: Optional[str] = None
    intent: str
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    prompt: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None
    analysis: Optional[VisionAnalysis] = None
    confidence: Optional[float] = None
    model_name: Optional[str] = None
    status: str = "received"
    confirmation_notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StorageItem(VisionBaseModel):
    storage_id: str
    name: str
    quantity: float
    unit: str
    expires_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class VisionIntakeRequest(VisionBaseModel):
    intent: str = Field(description="inventory_update|storage_update")
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    prompt: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class VisionConfirmationRequest(VisionBaseModel):
    intake_id: str
    approved: bool
    notes: Optional[str] = None
