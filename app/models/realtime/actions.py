"""
Action-related schema models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ActionStatus(str, Enum):
    """Status of an action execution."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    REQUIRES_MANUAL_REVIEW = "requires_manual_review"
    PENDING_USER = "pending_user"
    EXPIRED = "expired"


class ActionMetadata(BaseModel):
    """Metadata for action execution (audit trail)."""

    session_id: str
    user_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = Field(ge=0.0, le=1.0, default=0.8)
    requires_user_confirmation: bool = False
    audit_tags: List[str] = Field(default_factory=list)

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "session_id": "sess_9876",
            "user_id": "user_123",
            "timestamp": "2026-01-30T10:30:00Z",
            "confidence": 0.92,
            "requires_user_confirmation": True,
            "audit_tags": ["booking", "external_api"],
        }
    })


class Action(BaseModel):
    """Action that model intends to invoke (NOT executed by model)."""

    name: str = Field(description="Action name: search_listings, book_viewing, create_cv, etc.")
    id: str = Field(description="Unique action ID for tracking (e.g., act_12345)")
    params: Dict[str, Any] = Field(description="Action-specific parameters")
    metadata: ActionMetadata = Field(description="Audit metadata")

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "name": "search_listings",
            "id": "act_12345",
            "params": {
                "location": "Oslo, Norway",
                "price_min": 250000,
                "price_max": 450000,
                "beds_min": 2,
                "keywords": ["balcony", "near tram"],
                "radius_km": 5,
            },
            "metadata": {
                "session_id": "sess_9876",
                "user_id": "user_123",
                "confidence": 0.92,
                "requires_user_confirmation": False,
                "audit_tags": ["search", "property"],
            },
        }
    })


class ActionResult(BaseModel):
    """Result of action execution by Gateway."""

    type: str = Field(default="action.result")
    action_id: str = Field(description="Corresponding action ID")
    action_name: str = Field(description="Name of the action (for reference)")
    status: ActionStatus = Field(description="Success/failure status")
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    requires_manual_review: bool = False
    audit: Dict[str, Any] = Field(default_factory=dict)

    model_config: ConfigDict = ConfigDict(json_schema_extra={
        "example": {
            "type": "action.result",
            "action_id": "act_12345",
            "action_name": "search_listings",
            "status": "success",
            "result": {
                "listings": [
                    {
                        "id": "L1",
                        "title": "Cozy 2-bed with balcony",
                        "price": 380000,
                        "address": "Frogner, Oslo",
                        "coords": [59.9, 10.7],
                        "score": 0.95,
                    }
                ]
            },
            "audit": {
                "executed_at": "2026-01-30T10:30:00Z",
                "executor": "action_router",
                "external_provider": "zillow_adapter",
            },
        }
    })
