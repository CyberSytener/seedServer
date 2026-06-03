from __future__ import annotations

import pytest

from app.core.saga_blueprints import blueprint_store
from app.services.blueprint_gallery import seed_blueprint_gallery


@pytest.mark.asyncio
async def test_hot_offer_blueprint_seeded() -> None:
    await seed_blueprint_gallery()
    names = await blueprint_store.list_names()
    assert "hot_offer_flow" in names
