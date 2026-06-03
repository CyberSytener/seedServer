"""Tests for modules.bot.autotune — config grid generation and persistence."""
import json
import pytest
from pathlib import Path

from modules.bot.planner import PlannerConfig
from modules.bot.autotune import (
    generate_config_grid,
    save_best_config,
    load_best_config,
    AutotuneResult,
    BEST_CONFIGS_DIR,
)


# ── generate_config_grid ──────────────────────────────────────────────

class TestGenerateConfigGrid:
    def test_default_grid_not_empty(self):
        configs = generate_config_grid()
        assert len(configs) > 0

    def test_all_elements_are_planner_configs(self):
        configs = generate_config_grid()
        for c in configs:
            assert isinstance(c, PlannerConfig)

    def test_custom_params(self):
        configs = generate_config_grid(
            lookaheads=[1, 2],
            preview_weights=[3.0],
            auto_delivery_bonuses=[5.0],
            tiebreak_seeds=[0],
        )
        assert len(configs) == 2  # 2 × 1 × 1 × 1

    def test_grid_covers_combinations(self):
        configs = generate_config_grid(
            lookaheads=[1],
            preview_weights=[2.0, 5.0],
            auto_delivery_bonuses=[3.0],
            tiebreak_seeds=[0, 1],
        )
        assert len(configs) == 4  # 1 × 2 × 1 × 2
        pws = {c.preview_weight for c in configs}
        assert pws == {2.0, 5.0}
        seeds = {c.tiebreak_seed for c in configs}
        assert seeds == {0, 1}

    def test_default_grid_size(self):
        configs = generate_config_grid()
        # 3 × 2 × 3 × 3 = 54
        assert len(configs) == 54


# ── save / load best config ───────────────────────────────────────────

class TestConfigPersistence:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        # Redirect best configs dir to tmp
        monkeypatch.setattr(
            "modules.bot.autotune.BEST_CONFIGS_DIR", tmp_path
        )
        cfg = PlannerConfig(lookahead_orders=3, preview_weight=7.0)
        result = AutotuneResult(
            config=cfg, score=150, items_delivered=100,
            orders_completed=10, rounds_played=300,
            avg_decision_ms=0.5, run_index=0,
        )
        save_best_config("easy", cfg, result)
        loaded = load_best_config("easy")
        assert loaded.lookahead_orders == 3
        assert loaded.preview_weight == 7.0

    def test_load_missing_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "modules.bot.autotune.BEST_CONFIGS_DIR", tmp_path
        )
        loaded = load_best_config("nonexistent")
        assert loaded.lookahead_orders == PlannerConfig().lookahead_orders

    def test_save_creates_json_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "modules.bot.autotune.BEST_CONFIGS_DIR", tmp_path
        )
        cfg = PlannerConfig()
        result = AutotuneResult(
            config=cfg, score=100, items_delivered=80,
            orders_completed=4, rounds_played=300,
            avg_decision_ms=1.0, run_index=0,
        )
        path = save_best_config("medium", cfg, result)
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["score"] == 100
        assert "config" in data
