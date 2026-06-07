from __future__ import annotations

import json
from pathlib import Path

from app.cli import main


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


def test_seed_module_create_returns_structured_error_for_existing_package(tmp_path: Path, capsys) -> None:
    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 0
    capsys.readouterr()

    assert main(["module", "create", "cli_demo", "--root", str(tmp_path), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)

    assert report["ok"] is False
    assert report["diagnostics"][0]["code"] == "cli.request_failed"
