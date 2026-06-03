from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ReceiptItem(BaseModel):
    name: str
    original_name: Optional[str] = None
    canonical_name: Optional[str] = None
    qty: float = Field(default=1.0)
    unit: str = Field(default="pcs")
    price: float = Field(default=0.0)
    category: Optional[str] = None
    is_food: bool = True
    match_id: Optional[str] = None
    action: Optional[str] = None


class ReceiptExtractionResult(BaseModel):
    merchant_name: Optional[str] = None
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="NOK")
    items: List[ReceiptItem] = Field(default_factory=list)
    validation_passed: bool = False
    validation_errors: List[str] = Field(default_factory=list)


class ReceiptConfirmRequest(BaseModel):
    image_url: Optional[str] = None
    merchant_name: Optional[str] = None
    total_amount: float = Field(default=0.0)
    currency: str = Field(default="NOK")
    scanned_at: Optional[datetime] = None
    items: List[ReceiptItem] = Field(default_factory=list)


class ReceiptPersistResponse(BaseModel):
    receipt_id: str
    items_saved: int
    store_prices_updated: int
