from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FridgeItem(BaseModel):
    item_id: str = Field(description="Storage item id")
    name: str
    canonical_name: Optional[str] = None
    display_name: Optional[str] = None
    quantity: float
    unit: str
    expires_at: Optional[str] = None
    freshness_pct: Optional[int] = None
    days_to_expiry: Optional[int] = None
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class FridgeItemCreate(BaseModel):
    name: str
    canonical_name: Optional[str] = None
    display_name: Optional[str] = None
    quantity: float
    unit: str
    expires_at: Optional[str] = None
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class FridgeItemPatch(BaseModel):
    name: Optional[str] = None
    canonical_name: Optional[str] = None
    display_name: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    expires_at: Optional[str] = None
    category: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class StoreItem(BaseModel):
    item_id: str
    sku: Optional[str] = None
    name: str
    category: Optional[str] = None
    unit: Optional[str] = None
    quantity_available: Optional[float] = None
    last_price_paid: Optional[float] = None


class OrderItem(BaseModel):
    item_id: Optional[str] = None
    sku: Optional[str] = None
    name: Optional[str] = None
    quantity: float
    unit: Optional[str] = None
    price: Optional[float] = None


class OrderDelivery(BaseModel):
    address: Optional[str] = None
    window: Optional[str] = None
    instructions: Optional[str] = None


class OrderPayment(BaseModel):
    method_id: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None


class OrderInitRequest(BaseModel):
    items: List[OrderItem]
    delivery: Optional[OrderDelivery] = None
    payment: Optional[OrderPayment] = None
    notes: Optional[str] = None


class OrderInitResponse(BaseModel):
    order_id: str
    saga_id: str
    status: str


class OrderSummary(BaseModel):
    order_id: str
    saga_id: str
    status: str
    items: List[OrderItem]
    total: Optional[float] = None
    currency: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    type: str = "order_status"
    order_id: str
    saga_id: str
    status: str
    message: Optional[str] = None
    timestamp: str


class VisionDetectedItem(BaseModel):
    id: Optional[str] = None
    detection_id: Optional[str] = None
    icon_key: Optional[str] = None
    dedupe_key: Optional[str] = None
    name: str
    canonical_name: Optional[str] = None
    display_name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    quantity: float
    unit: str
    expires_at: Optional[str] = None
    confidence: Optional[float] = None
    confidence_score: Optional[float] = None
    trust_level: Optional[str] = None
    review_required: Optional[bool] = None
    duplicate_count: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    center_x: Optional[float] = None
    center_y: Optional[float] = None
    bbox_x: Optional[float] = None
    bbox_y: Optional[float] = None
    bbox_width: Optional[float] = None
    bbox_height: Optional[float] = None
    coordinates: Optional[Dict[str, float]] = None
    bbox: Optional[Dict[str, float]] = None


class HybridRecipeSuggestion(BaseModel):
    recipe_id: str
    name: str
    description: Optional[str] = None
    available_items: List[str] = Field(default_factory=list)
    missing_items: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
