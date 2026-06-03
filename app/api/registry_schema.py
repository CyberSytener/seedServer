from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.core.blocks import get_registry_schema


router = APIRouter(prefix="/registry", tags=["Registry"])


@router.get("/schema")
async def get_registry_schema_endpoint() -> Dict[str, Any]:
    return get_registry_schema()
