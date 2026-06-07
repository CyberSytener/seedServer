from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from app.module_sdk import (
    create_module_package,
    resolve_module_package,
    run_module_package_tests,
    sandbox_module_package,
    validate_module_package,
)


def _print_report(report: Dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    state = "OK" if report.get("ok") else "FAIL"
    print(f"[{state}] {report.get('module_id') or report.get('manifest') or 'module'}")
    for diagnostic in report.get("diagnostics") or []:
        print(f"  - [{diagnostic['code']}] {diagnostic['path']}: {diagnostic['message']}")
    if "passed" in report:
        print(f"  golden cases: {report.get('passed', 0)} passed, {report.get('failed', 0)} failed")


def _module_create(args: argparse.Namespace) -> int:
    package = create_module_package(
        args.module_id,
        registry_root=Path(args.root),
        title=args.title,
        description=args.description,
        force=args.force,
    )
    report = validate_module_package(package)
    report["created"] = str(package.root)
    _print_report(report, as_json=args.json)
    return 0 if report["ok"] else 1


def _module_validate(args: argparse.Namespace) -> int:
    package = resolve_module_package(args.target, registry_root=Path(args.root))
    report = validate_module_package(package)
    _print_report(report, as_json=args.json)
    return 0 if report["ok"] else 1


def _module_test(args: argparse.Namespace) -> int:
    package = resolve_module_package(args.target, registry_root=Path(args.root))
    report = run_module_package_tests(package)
    _print_report(report, as_json=args.json)
    return 0 if report["ok"] else 1


def _load_sandbox_input(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    if args.input_json and args.input_file:
        raise ValueError("use either --input or --input-file, not both")
    if args.input_file:
        data = json.loads(Path(args.input_file).read_text(encoding="utf-8-sig"))
    elif args.input_json:
        data = json.loads(args.input_json)
    else:
        return None
    if not isinstance(data, dict):
        raise ValueError("sandbox input must be a JSON object")
    return data


def _module_sandbox(args: argparse.Namespace) -> int:
    package = resolve_module_package(args.target, registry_root=Path(args.root))
    report = sandbox_module_package(
        package,
        inputs=_load_sandbox_input(args),
        timeout_seconds=args.timeout_seconds,
    )
    _print_report(report, as_json=args.json)
    return 0 if report["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="seed", description="Seed Platform developer CLI")
    commands = parser.add_subparsers(dest="command", required=True)
    module = commands.add_parser("module", help="Create and inspect module packages")
    module_commands = module.add_subparsers(dest="module_command", required=True)

    create = module_commands.add_parser("create", help="Create a new SDK module package")
    create.add_argument("module_id")
    create.add_argument("--root", default="modules")
    create.add_argument("--title")
    create.add_argument("--description")
    create.add_argument("--force", action="store_true")
    create.add_argument("--json", action="store_true")
    create.set_defaults(handler=_module_create)

    for name, help_text, handler in (
        ("validate", "Validate a module manifest and package", _module_validate),
        ("test", "Run declared golden cases through the SDK handler", _module_test),
    ):
        command = module_commands.add_parser(name, help=help_text)
        command.add_argument("target")
        command.add_argument("--root", default="modules")
        command.add_argument("--json", action="store_true")
        command.set_defaults(handler=handler)

    sandbox = module_commands.add_parser("sandbox", help="Run an SDK module in an isolated subprocess")
    sandbox.add_argument("target")
    sandbox.add_argument("--root", default="modules")
    sandbox.add_argument("--input", dest="input_json")
    sandbox.add_argument("--input-file")
    sandbox.add_argument("--timeout-seconds", type=float)
    sandbox.add_argument("--json", action="store_true")
    sandbox.set_defaults(handler=_module_sandbox)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        report = {
            "ok": False,
            "diagnostics": [
                {
                    "code": "cli.request_failed",
                    "path": "$",
                    "message": str(exc),
                }
            ],
        }
        _print_report(report, as_json=bool(getattr(args, "json", False)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
