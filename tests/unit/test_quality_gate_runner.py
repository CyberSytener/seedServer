from __future__ import annotations

from scripts import run_quality_gate as quality_gate


EXPECTED_INTENT_TO_OUTCOME_TESTS = [
    "tests/unit/test_quality_gate_runner.py",
    "tests/unit/opportunity",
    "tests/unit/test_flow_graph.py",
    "tests/unit/test_flow_contract_validator.py",
    "tests/unit/realtime/test_flow_executor_import_boundary.py",
    "tests/unit/realtime/test_flow_cycle_rejection.py",
    "tests/integration/opportunity",
]


def test_candidate_gate_inventory_is_focused_and_versioned() -> None:
    assert quality_gate.INTENT_TO_OUTCOME_TESTS == EXPECTED_INTENT_TO_OUTCOME_TESTS
    assert "intent-to-outcome" in quality_gate.GATE_CHOICES
    assert "tests/unit/opportunity" not in quality_gate.PORTFOLIO_TESTS
    assert "tests/unit" not in quality_gate.INTENT_TO_OUTCOME_TESTS
    assert "tests/integration" not in quality_gate.INTENT_TO_OUTCOME_TESTS


def test_candidate_gate_validates_docs_before_running_tests(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    def fake_run(command: list[str]) -> int:
        calls.append(("run", command))
        return 0

    def fake_pytest(paths: list[str]) -> int:
        calls.append(("pytest", paths))
        return 0

    monkeypatch.setattr(quality_gate, "_run", fake_run)
    monkeypatch.setattr(quality_gate, "_pytest", fake_pytest)

    assert quality_gate.run_gate("intent-to-outcome") == 0
    assert calls == [
        (
            "run",
            [quality_gate.sys.executable, "scripts/validate_active_docs.py"],
        ),
        ("pytest", EXPECTED_INTENT_TO_OUTCOME_TESTS),
    ]


def test_candidate_gate_stops_when_documentation_validation_fails(monkeypatch) -> None:
    pytest_calls: list[list[str]] = []

    monkeypatch.setattr(quality_gate, "_run", lambda _command: 23)
    monkeypatch.setattr(
        quality_gate,
        "_pytest",
        lambda paths: pytest_calls.append(paths) or 0,
    )

    assert quality_gate.run_gate("intent-to-outcome") == 23
    assert pytest_calls == []


def test_unknown_gate_still_fails_explicitly() -> None:
    try:
        quality_gate.run_gate("unknown")
    except ValueError as exc:
        assert str(exc) == "Unknown gate: unknown"
    else:
        raise AssertionError("unknown gate must raise ValueError")
