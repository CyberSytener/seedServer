"""Game protocol models for NMiAI Grocery Bot.

Re-exports the canonical models from ``modules.bot.models`` and adds
thin convenience wrappers for the integration layer.  No duplication —
the single source of truth lives in ``modules/bot/models.py``.
"""
from __future__ import annotations

# Re-export every model the game loop needs
from modules.bot.models import (           # noqa: F401
    BotAction,
    BotActionCommand,
    BotInfo,
    GameOver,
    GameState,
    GridInfo,
    ItemInfo,
    OrderInfo,
    OrderStatus,
    Pos,
    RoundActions,
)

__all__ = [
    "BotAction",
    "BotActionCommand",
    "BotInfo",
    "GameOver",
    "GameState",
    "GridInfo",
    "ItemInfo",
    "OrderInfo",
    "OrderStatus",
    "Pos",
    "RoundActions",
]
