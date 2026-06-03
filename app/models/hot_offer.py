"""
Hot Offer models
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SalesStat(BaseModel):
    stat_id: str
    location_id: Optional[str] = None
    day_of_week: int
    hour_of_day: int
    category: Optional[str] = None
    recipe_name: Optional[str] = None
    avg_units_sold: Optional[float] = None
    created_at: Optional[datetime] = None


class PendingOffer(BaseModel):
    offer_id: str
    status: str
    offer_payload: Dict[str, Any]
    validation_scores: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class HotOffer(BaseModel):
    offer_id: str
    name: Optional[str] = None
    slogan: Optional[str] = None
    ingredients: List[str] = Field(default_factory=list)
    cogs_total: Optional[float] = None
    currency: Optional[str] = None
    price: Optional[float] = None
    margin_pct: Optional[float] = None
    waste_overhead: Optional[float] = None


class HotOfferHistory(BaseModel):
    offer_id: str
    status: str
    offer_payload: Dict[str, Any]
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
