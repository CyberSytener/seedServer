"""Tests for modules.bot.models — Pydantic game state parsing."""
import pytest
from modules.bot.models import (
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

# ── Sample payload (from challenge spec) ────────────────────────────────

SAMPLE_STATE = {
    "type": "game_state",
    "round": 42,
    "max_rounds": 300,
    "grid": {
        "width": 16,
        "height": 12,
        "walls": [[1, 1], [1, 2], [3, 1]],
    },
    "bots": [
        {"id": 0, "position": [3, 7], "inventory": ["milk"]},
        {"id": 1, "position": [5, 3], "inventory": []},
        {"id": 2, "position": [10, 7], "inventory": ["bread", "eggs"]},
    ],
    "items": [
        {"id": "item_0", "type": "milk", "position": [2, 1]},
        {"id": "item_1", "type": "bread", "position": [4, 1]},
    ],
    "orders": [
        {
            "id": "order_0",
            "items_required": ["milk", "bread", "eggs"],
            "items_delivered": ["milk"],
            "complete": False,
            "status": "active",
        },
        {
            "id": "order_1",
            "items_required": ["cheese", "butter"],
            "items_delivered": [],
            "complete": False,
            "status": "preview",
        },
    ],
    "drop_off": [1, 10],
    "score": 12,
}


class TestPos:
    def test_equality(self):
        assert Pos(3, 7) == Pos(3, 7)
        assert Pos(3, 7) != Pos(3, 8)

    def test_tuple_equality(self):
        assert Pos(3, 7) == (3, 7)
        assert Pos(3, 7) == [3, 7]

    def test_hash(self):
        s = {Pos(1, 2), Pos(1, 2), Pos(3, 4)}
        assert len(s) == 2

    def test_manhattan(self):
        assert Pos(0, 0).manhattan(Pos(3, 4)) == 7
        assert Pos(5, 5).manhattan(Pos(5, 5)) == 0


class TestGameState:
    def test_parse_sample(self):
        state = GameState(**SAMPLE_STATE)
        assert state.round == 42
        assert state.max_rounds == 300
        assert state.score == 12
        assert len(state.bots) == 3
        assert len(state.items) == 2
        assert len(state.orders) == 2
        assert state.drop_off == [1, 10]

    def test_grid(self):
        state = GameState(**SAMPLE_STATE)
        assert state.grid.width == 16
        assert state.grid.height == 12
        assert len(state.grid.walls) == 3

    def test_bot_pos(self):
        state = GameState(**SAMPLE_STATE)
        assert state.bots[0].pos == Pos(3, 7)
        assert state.bots[0].inventory == ["milk"]

    def test_item_pos(self):
        state = GameState(**SAMPLE_STATE)
        assert state.items[0].pos == Pos(2, 1)
        assert state.items[0].type == "milk"

    def test_order_status(self):
        state = GameState(**SAMPLE_STATE)
        assert state.orders[0].status == OrderStatus.ACTIVE
        assert state.orders[1].status == OrderStatus.PREVIEW

    def test_drop_off_pos(self):
        state = GameState(**SAMPLE_STATE)
        assert state.drop_off_pos == Pos(1, 10)


class TestGameOver:
    def test_parse(self):
        go = GameOver(type="game_over", score=99, items=15, orders=3)
        assert go.score == 99


class TestRoundActions:
    def test_serialize(self):
        actions = RoundActions(actions=[
            BotActionCommand(bot=0, action=BotAction.MOVE_UP),
            BotActionCommand(bot=1, action=BotAction.PICK_UP, item_id="item_3"),
            BotActionCommand(bot=2, action=BotAction.DROP_OFF),
        ])
        payload = actions.to_payload()
        assert len(payload["actions"]) == 3
        assert payload["actions"][0] == {"bot": 0, "action": "move_up"}
        assert payload["actions"][1] == {"bot": 1, "action": "pick_up", "item_id": "item_3"}
        assert payload["actions"][2] == {"bot": 2, "action": "drop_off"}

    def test_roundtrip(self):
        """Parse a game state, produce actions, serialize back."""
        state = GameState(**SAMPLE_STATE)
        actions = RoundActions(actions=[
            BotActionCommand(bot=b.id, action=BotAction.WAIT)
            for b in state.bots
        ])
        payload = actions.to_payload()
        assert all(a["action"] == "wait" for a in payload["actions"])
