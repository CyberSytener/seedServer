from __future__ import annotations

import json
from pathlib import Path

from app.cli import main
from app.module_sdk import (
    create_module_package,
    qualify_module_package,
    record_module_evidence,
    sandbox_module_package,
    transition_module_lifecycle,
)


def test_seed_module_create_validate_test_and_sandbox(tmp_path: Path, capsys) -> None:
    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    create_report = json.loads(capsys.readouterr().out)
    assert create_report["ok"] is True

    assert main(["module", "validate", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    validate_report = json.loads(capsys.readouterr().out)
    assert validate_report["module_id"] == "cli_demo"

    assert main(["module", "test", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    test_report = json.loads(capsys.readouterr().out)
    assert test_report["passed"] == 1

    assert (
        main(
            [
                "module",
                "sandbox",
                "cli_demo",
                "--root",
                str(tmp_path),
                "--input",
                '{"request":"sandbox"}',
                "--json",
            ]
        )
        == 0
    )
    sandbox_report = json.loads(capsys.readouterr().out)
    assert sandbox_report["result"]["output"] == {"result": "sandbox"}


def test_seed_module_sandbox_rejects_non_object_input(tmp_path: Path, capsys) -> None:
    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "module",
                "sandbox",
                "cli_demo",
                "--root",
                str(tmp_path),
                "--input",
                "[]",
                "--json",
            ]
        )
        == 1
    )
    report = json.loads(capsys.readouterr().out)

    assert report["diagnostics"][0]["code"] == "cli.request_failed"


def test_seed_module_sandbox_accepts_utf8_bom_input_file(tmp_path: Path, capsys) -> None:
    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    input_path = tmp_path / "input.json"
    input_path.write_text('{"request":"from file"}', encoding="utf-8-sig")

    assert (
        main(
            [
                "module",
                "sandbox",
                "cli_demo",
                "--root",
                str(tmp_path),
                "--input-file",
                str(input_path),
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)

    assert report["result"]["output"] == {"result": "from file"}


def test_seed_module_sandbox_selects_docker_runtime(tmp_path: Path, capsys, monkeypatch) -> None:
    assert main(["module", "create", "cli_docker", "--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()
    captured = {}

    def fake_sandbox(_package, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "module_id": "cli_docker", "diagnostics": []}

    monkeypatch.setattr("app.cli.sandbox_module_package", fake_sandbox)

    assert (
        main(
            [
                "module",
                "sandbox",
                "cli_docker",
                "--root",
                str(tmp_path),
                "--runtime",
                "docker",
                "--image",
                "custom-sandbox:test",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert captured["runtime"] == "docker"
    assert captured["image"] == "custom-sandbox:test"


def test_seed_module_qualify_and_status_use_matching_evidence(tmp_path: Path, capsys) -> None:
    modules_root = tmp_path / "modules"
    evidence_root = tmp_path / "evidence"
    assert main(["module", "create", "cli_evidence", "--root", str(modules_root), "--json"]) == 0
    capsys.readouterr()

    assert (
        main(
            [
                "module",
                "qualify",
                "cli_evidence",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--json",
            ]
        )
        == 0
    )
    qualification = json.loads(capsys.readouterr().out)
    assert qualification["approval_ready"] is True
    assert len(qualification["qualification_records"]) == 3

    assert (
        main(
            [
                "module",
                "transition",
                "cli_evidence",
                "validated",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--actor",
                "cli-reviewer",
                "--reason",
                "validation evidence passed",
                "--json",
            ]
        )
        == 0
    )
    transition = json.loads(capsys.readouterr().out)
    assert transition["lifecycle"] == "validated"

    assert (
        main(
            [
                "module",
                "status",
                "cli_evidence",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--json",
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)
    assert status["approval_ready"] is True
    assert status["evidence"]["matching_count"] == 4

    handler = modules_root / "cli_evidence" / "handler.py"
    handler.write_text(handler.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    assert (
        main(
            [
                "module",
                "status",
                "cli_evidence",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--json",
            ]
        )
        == 1
    )
    stale_status = json.loads(capsys.readouterr().out)
    assert stale_status["evidence"]["stale_count"] == 4


def test_seed_module_create_returns_structured_error_for_existing_package(tmp_path: Path, capsys) -> None:
    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()

    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)

    assert report["ok"] is False
    assert report["diagnostics"][0]["code"] == "cli.request_failed"


def test_seed_module_publish_reads_authority_key_from_environment(tmp_path: Path, capsys, monkeypatch) -> None:
    modules_root = tmp_path / "modules"
    evidence_root = tmp_path / "evidence"
    versions_root = tmp_path / "versions"
    signing_key = "cli-publish-authority-" + "a" * 32
    package = create_module_package("cli_publish", registry_root=modules_root)
    qualify_module_package(package, evidence_root=evidence_root)
    hardened = sandbox_module_package(package, inputs={"request": "hardened"})
    hardened["evidence"]["runtime"] = {"adapter": "docker", "image": "fixture", "engine_version": "fixture"}
    hardened["evidence"]["limits"].update(
        {
            "network_enforced": True,
            "filesystem_enforced": True,
            "read_only_rootfs": True,
            "capabilities_dropped": True,
            "no_new_privileges": True,
            "non_root_user": True,
            "memory_enforced": True,
            "process_limit_enforced": True,
        }
    )
    hardened["evidence"]["capability_report"] = {
        "enforcement": "python_audit_hook",
        "policy": {},
        "operations": [],
        "operation_count": 0,
        "violation_count": 0,
        "truncated": False,
    }
    record_module_evidence(
        package,
        kind="sandbox",
        report=hardened,
        evidence_root=evidence_root,
        signing_key=signing_key,
    )
    for target in ("validated", "tested", "sandboxed", "approved"):
        transition_module_lifecycle(
            package,
            target=target,
            actor="cli-reviewer",
            reason=f"advance to {target}",
            evidence_root=evidence_root,
            signing_key=signing_key,
        )
    monkeypatch.setenv("SEED_MODULE_EVIDENCE_SIGNING_KEY", signing_key)

    assert (
        main(
            [
                "module",
                "publish",
                "cli_publish",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--versions-root",
                str(versions_root),
                "--actor",
                "release-manager",
                "--reason",
                "publish signed module",
                "--json",
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)

    assert report["decision"] == "allow"
    assert report["lifecycle"] == "published"
    assert report["publish_evidence"]["signature"]["algorithm"] == "hmac-sha256"

    assert (
        main(
            [
                "module",
                "history",
                "cli_publish",
                "--versions-root",
                str(versions_root),
                "--json",
            ]
        )
        == 0
    )
    history = json.loads(capsys.readouterr().out)
    assert history["version_count"] == 1
    assert history["versions"][0]["module"]["fingerprint"] == report["fingerprint"]

    assert (
        main(
            [
                "module",
                "deprecate",
                "cli_publish",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--versions-root",
                str(versions_root),
                "--actor",
                "release-manager",
                "--reason",
                "replaced by next release",
                "--replacement-version",
                "0.2.0",
                "--json",
            ]
        )
        == 0
    )
    deprecated = json.loads(capsys.readouterr().out)
    assert deprecated["lifecycle"] == "deprecated"
    assert deprecated["deprecation_record"]["signature_status"] == "valid"

    assert (
        main(
            [
                "module",
                "history",
                "cli_publish",
                "--versions-root",
                str(versions_root),
                "--json",
            ]
        )
        == 0
    )
    deprecated_history = json.loads(capsys.readouterr().out)
    assert deprecated_history["versions"][0]["lifecycle"] == "deprecated"
    assert deprecated_history["versions"][0]["latest_deprecation"]["replacement_version"] == "0.2.0"


def test_seed_module_reject_and_rejections_preserve_repair_context(tmp_path: Path, capsys, monkeypatch) -> None:
    modules_root = tmp_path / "modules"
    evidence_root = tmp_path / "evidence"
    rejections_root = tmp_path / "rejections"
    signing_key = "cli-rejection-authority-" + "a" * 32
    assert main(["module", "create", "cli_rejection", "--root", str(modules_root), "--json"]) == 0
    capsys.readouterr()
    handler = modules_root / "cli_rejection" / "handler.py"
    handler.write_text(handler.read_text(encoding="utf-8") + "\nimport httpx\n", encoding="utf-8")
    monkeypatch.setenv("SEED_MODULE_EVIDENCE_SIGNING_KEY", signing_key)

    assert (
        main(
            [
                "module",
                "reject",
                "cli_rejection",
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--rejections-root",
                str(rejections_root),
                "--actor",
                "cli-reviewer",
                "--reason",
                "repair undeclared dependency",
                "--json",
            ]
        )
        == 0
    )
    rejected = json.loads(capsys.readouterr().out)
    assert rejected["decision"] == "reject"
    assert any(item["code"] == "sdk.dependency_not_allowed" for item in rejected["repair_context"]["diagnostics"])

    assert (
        main(
            [
                "module",
                "rejections",
                "cli_rejection",
                "--rejections-root",
                str(rejections_root),
                "--json",
            ]
        )
        == 0
    )
    history = json.loads(capsys.readouterr().out)
    assert history["rejection_count"] == 1
    assert history["rejections"][0]["decision"]["reason"] == "repair undeclared dependency"

    rejection_id = history["rejections"][0]["rejection_id"]
    assert (
        main(
            [
                "module",
                "repair-plan",
                "cli_rejection",
                "--rejection-id",
                rejection_id,
                "--rejections-root",
                str(rejections_root),
                "--json",
            ]
        )
        == 0
    )
    plan = json.loads(capsys.readouterr().out)
    assert plan["budget"]["attempts_remaining"] == 3
    assert plan["constraints"]["publish_allowed"] is False

    handler.write_text(
        handler.read_text(encoding="utf-8").replace("import httpx", "# repaired"),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "module",
                "repair-check",
                "cli_rejection",
                "--rejection-id",
                rejection_id,
                "--root",
                str(modules_root),
                "--evidence-root",
                str(evidence_root),
                "--rejections-root",
                str(rejections_root),
                "--actor",
                "cli-reviewer",
                "--generator",
                "stub-builder",
                "--input",
                '{"request":"repaired through CLI"}',
                "--json",
            ]
        )
        == 0
    )
    repaired = json.loads(capsys.readouterr().out)
    assert repaired["ok"] is True
    assert repaired["repair_attempt"]["attempt"] == 1
    assert repaired["qualification"]["checks"]["sandbox"]["passed"] is True
