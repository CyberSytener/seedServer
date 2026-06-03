"""Tests for app.integrations.nmiai_grocery_bot — endpoint + protocol."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

# ── endpoint tests ─────────────────────────────────────────────────────────

from app.integrations.nmiai_grocery_bot.endpoint import (
    DIFFICULTY_MAP_IDS,
    GameSession,
    MapInfo,
    _load_access_token,
    list_maps,
    request_game_session,
)


class TestLoadAccessToken:
    """Verify .env token parsing."""

    def test_strips_cookie_prefix(self, monkeypatch):
        monkeypatch.setenv("AINM_ACCESS_TOKEN", "access_token=abc123.jwt.sig")
        assert _load_access_token() == "abc123.jwt.sig"

    def test_bare_jwt_passthrough(self, monkeypatch):
        monkeypatch.setenv("AINM_ACCESS_TOKEN", "abc123.jwt.sig")
        assert _load_access_token() == "abc123.jwt.sig"

    def test_missing_raises(self, monkeypatch):
        monkeypatch.delenv("AINM_ACCESS_TOKEN", raising=False)
        # Also patch dotenv so it doesn't load the real .env
        with patch("app.integrations.nmiai_grocery_bot.endpoint.load_dotenv"):
            with pytest.raises(EnvironmentError, match="AINM_ACCESS_TOKEN not set"):
                _load_access_token()


class TestDifficultyMapIds:
    """Verify well-known map IDs cover all four difficulties."""

    def test_four_difficulties(self):
        assert set(DIFFICULTY_MAP_IDS.keys()) == {"easy", "medium", "hard", "expert"}

    def test_ids_are_uuid_shaped(self):
        import re
        uuid_re = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        )
        for diff, mid in DIFFICULTY_MAP_IDS.items():
            assert uuid_re.match(mid), f"{diff} map_id is not a valid UUID: {mid}"


class TestListMaps:
    """Mock the HTTP call and verify parsing."""

    @patch("app.integrations.nmiai_grocery_bot.endpoint.requests.get")
    def test_returns_map_infos(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"id": "aaa", "label": "Easy", "difficulty": "easy", "seed": 7001},
            {"id": "bbb", "label": "Hard", "difficulty": "hard"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        maps = list_maps(access_token="fake-jwt")
        assert len(maps) == 2
        assert maps[0].label == "Easy"
        assert maps[0].seed == 7001
        assert maps[1].seed is None

        # Verify auth cookie was sent
        call_kwargs = mock_get.call_args
        assert "Cookie" in call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))


class TestRequestGameSession:
    """Mock the POST /games/request call."""

    @patch("app.integrations.nmiai_grocery_bot.endpoint.requests.post")
    def test_easy_session(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "token": "game-jwt-abc",
            "ws_url": "wss://game.ainm.no/ws?token=game-jwt-abc",
            "map": {
                "id": DIFFICULTY_MAP_IDS["easy"],
                "label": "Easy",
                "difficulty": "easy",
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        session = request_game_session("easy", access_token="fake-jwt")
        assert isinstance(session, GameSession)
        assert session.ws_url.startswith("wss://")
        assert session.difficulty == "easy"
        assert session.token == "game-jwt-abc"

        # Verify correct map_id was posted
        call_args = mock_post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body == {"map_id": DIFFICULTY_MAP_IDS["easy"]}

    @patch("app.integrations.nmiai_grocery_bot.endpoint.requests.post")
    def test_explicit_map_id(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "token": "t",
            "ws_url": "wss://x",
            "map": {"id": "custom-id", "label": "Custom", "difficulty": "hard"},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        session = request_game_session("hard", map_id="custom-id", access_token="jwt")
        assert session.map_id == "custom-id"

    def test_invalid_difficulty_raises(self):
        with pytest.raises(ValueError, match="Unknown difficulty"):
            request_game_session("nightmare", access_token="jwt")


# ── protocol tests ─────────────────────────────────────────────────────────

from app.integrations.nmiai_grocery_bot.protocol import (
    BotAction,
    BotActionCommand,
    GameOver,
    GameState,
    RoundActions,
)


class TestProtocolReExports:
    """Verify that protocol.py re-exports the canonical models."""

    def test_bot_action_values(self):
        assert BotAction.MOVE_UP.value == "move_up"
        assert BotAction.PICK_UP.value == "pick_up"
        assert BotAction.DROP_OFF.value == "drop_off"
        assert BotAction.WAIT.value == "wait"

    def test_round_actions_serialisation(self):
        actions = RoundActions(actions=[
            BotActionCommand(bot=0, action=BotAction.MOVE_UP),
            BotActionCommand(bot=1, action=BotAction.PICK_UP, item_id="i1"),
        ])
        payload = actions.to_payload()
        assert len(payload["actions"]) == 2
        assert payload["actions"][0] == {"bot": 0, "action": "move_up"}
        assert payload["actions"][1] == {"bot": 1, "action": "pick_up", "item_id": "i1"}

    def test_game_state_parse(self):
        raw = {
            "type": "game_state",
            "round": 0,
            "max_rounds": 300,
            "grid": {"width": 5, "height": 5, "walls": [[0, 0], [1, 1]]},
            "bots": [{"id": 0, "position": [2, 2], "inventory": []}],
            "items": [{"id": "i1", "type": "butter", "position": [1, 0]}],
            "orders": [{
                "id": "o1",
                "items_required": ["butter"],
                "items_delivered": [],
                "complete": False,
                "status": "active",
            }],
            "drop_off": [3, 3],
            "score": 0,
        }
        state = GameState(**raw)
        assert state.round == 0
        assert state.bots[0].pos.as_tuple() == (2, 2)
        assert state.items[0].type == "butter"

    def test_game_over_parse(self):
        go = GameOver(type="game_over", score=42, items=10, orders=3)
        assert go.score == 42


# ── ws_client tests (unit, no real WS) ────────────────────────────────────

from app.integrations.nmiai_grocery_bot.ws_client import GameResult


class TestGameResult:
    """Verify GameResult dataclass defaults."""

    def test_defaults(self):
        r = GameResult()
        assert r.score == 0
        assert r.rounds_played == 0
        assert r.error is None
        assert r.decision_times == []

    def test_with_values(self):
        r = GameResult(score=42, difficulty="hard", rounds_played=300)
        assert r.score == 42
        assert r.difficulty == "hard"
