from __future__ import annotations

import json
from pathlib import Path

from app.core.blocks import BlockRegistry
from app.services.dynamic_block_loader import DynamicBlockLoader
from app.services.dynamic_publish_gate import evaluate_publish_gate, record_publish_decision


def test_publish_gate_allows_non_production_with_required_checks(monkeypatch):
    monkeypatch.setenv("SEED_ENV", "development")
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_SIMULATION", raising=False)
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_APPROVAL", raising=False)

    gate = evaluate_publish_gate(
        dry_run_result={"status": "succeeded"},
        capability_scan={"required_capabilities": ["compute"], "violations": [], "passed": True},
        simulation_result=None,
        approval_token=None,
    )

    assert gate["can_register"] is True
    assert gate["decision"] == "allow"
    assert gate["checks"]["simulation"]["required"] is False
    assert gate["checks"]["approval"]["required"] is False


def test_publish_gate_blocks_production_without_simulation_and_approval(monkeypatch):
    monkeypatch.setenv("SEED_ENV", "production")
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_SIMULATION", raising=False)
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_APPROVAL", raising=False)

    gate = evaluate_publish_gate(
        dry_run_result={"status": "succeeded"},
        capability_scan={"required_capabilities": ["compute"], "violations": [], "passed": True},
        simulation_result=None,
        approval_token=None,
    )

    assert gate["can_register"] is False
    assert gate["decision"] == "block"
    assert gate["checks"]["simulation"]["required"] is True
    assert gate["checks"]["approval"]["required"] is True


def test_publish_gate_allows_production_when_all_required_checks_pass(monkeypatch):
    monkeypatch.setenv("SEED_ENV", "production")
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_SIMULATION", raising=False)
    monkeypatch.delenv("SEED_DYNAMIC_BLOCK_REQUIRE_APPROVAL", raising=False)

    gate = evaluate_publish_gate(
        dry_run_result={"status": "succeeded"},
        capability_scan={"required_capabilities": ["compute"], "violations": [], "passed": True},
        simulation_result={"status": "passed", "passed": True, "artifact_ref": "sim/report.json"},
        approval_token="approved-by-admin",
    )

    assert gate["can_register"] is True
    assert gate["decision"] == "allow"


def test_publish_gate_blocks_disallowed_capability(monkeypatch):
    monkeypatch.setenv("SEED_ENV", "development")
    monkeypatch.setenv("SEED_DYNAMIC_BLOCK_ALLOWED_CAPABILITIES", "compute")

    gate = evaluate_publish_gate(
        dry_run_result={"status": "succeeded"},
        capability_scan={"required_capabilities": ["network"], "violations": [], "passed": True},
        simulation_result=None,
        approval_token=None,
    )

    assert gate["can_register"] is False
    assert gate["checks"]["capability_scan"]["passed"] is False
    assert gate["checks"]["capability_scan"]["disallowed_capabilities"] == ["network"]


def test_publish_gate_audit_is_persisted(tmp_path, monkeypatch):
    audit_file = tmp_path / "audit" / "dynamic_publish.jsonl"
    monkeypatch.setenv("SEED_DYNAMIC_PUBLISH_AUDIT_LOG", str(audit_file))

    gate_report = evaluate_publish_gate(
        dry_run_result={"status": "succeeded"},
        capability_scan={"required_capabilities": ["compute"], "violations": [], "passed": True},
        simulation_result=None,
        approval_token=None,
    )

    written_path = record_publish_decision(
        block_name="demo_block",
        actor_id="admin_user",
        gate_report=gate_report,
        extra={"source": "unit_test"},
    )
    assert Path(written_path).exists()

    lines = Path(written_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["block_name"] == "demo_block"
    assert payload["actor_id"] == "admin_user"
    assert payload["decision"] in {"allow", "block"}


def test_dynamic_loader_capability_scan_reports_compute_for_safe_code():
    loader = DynamicBlockLoader(BlockRegistry())
    scan = loader.scan_capabilities(
        """
from typing import Dict

class DemoBlock(BlockBase):
    DESCRIPTION = "demo"
    INPUT_SCHEMA = {"type":"object","properties":{"value":{"type":"string"}},"required":["value"]}
    OUTPUT_SCHEMA = {"type":"object","properties":{"echo":{"type":"string"}},"required":["echo"]}

    async def execute(self, context, inputs):
        return {"echo": inputs.get("value", "")}
"""
    )
    assert scan["passed"] is True
    assert "compute" in scan["required_capabilities"]


def test_dynamic_loader_capability_scan_reports_violations_for_forbidden_import():
    loader = DynamicBlockLoader(BlockRegistry())
    scan = loader.scan_capabilities(
        """
import socket

class DemoBlock(BlockBase):
    DESCRIPTION = "demo"
    INPUT_SCHEMA = {"type":"object","properties":{"value":{"type":"string"}},"required":["value"]}
    OUTPUT_SCHEMA = {"type":"object","properties":{"echo":{"type":"string"}},"required":["echo"]}

    async def execute(self, context, inputs):
        return {"echo": inputs.get("value", "")}
"""
    )
    assert scan["passed"] is False
    assert any("forbidden_import" in entry for entry in scan["violations"])
