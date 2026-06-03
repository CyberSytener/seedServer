#!/usr/bin/env python3
"""Helper: register a created dependency in `CREATED_DEPENDENCIES.md` and optionally add to `requirements.txt`.

Usage:
  python scripts/register_dependency.py "package==1.2.3" "Reason / files / PR#"
  python scripts/register_dependency.py "package" "Reason" --requirements

This is a small convenience tool to keep the CREATED_DEPENDENCIES.md up to date and to avoid ad-hoc edits.
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "CREATED_DEPENDENCIES.md"
REQ = ROOT / "requirements.txt"


def append_md(package: str, version: str, reason: str) -> None:
    date = datetime.date.today().isoformat()
    import_name = package.split("==")[0]
    # Basic markdown row
    row = f"| {date} | {package} | {version or '-'} | {import_name} | {reason} | - |\n"

    with MD.open("a", encoding="utf-8") as f:
        f.write(row)
    print(f"✅ Appended to {MD}: {package} — {reason}")


def append_changelog(package: str, version: str, reason: str) -> None:
    """Append a concise entry to DEPENDENCY_CHANGELOG.md with timestamp and user."""
    import getpass
    import datetime as _dt

    LOG = ROOT / "DEPENDENCY_CHANGELOG.md"

    if not LOG.exists():
        # create with header if missing
        LOG.write_text("Timestamp (UTC) | Package | Version | User | Reason\n---\n", encoding="utf-8")

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    user = getpass.getuser()
    ver = version or "-"
    entry = f"{ts} | {package} | {ver} | {user} | {reason}\n"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(entry)
    print(f"✅ Recorded changelog entry in {LOG}: {package} — {reason}")

# Record changelog when adding to the MD file so the change is recorded automatically
append_changelog(package, version, reason)


def add_to_requirements(package: str) -> None:
    if not REQ.exists():
        print(f"⚠️  {REQ} not found; create it or add the package manually.")
        return
    content = REQ.read_text(encoding="utf-8")
    if package in content:
        print(f"ℹ️  {package} already present in requirements.txt")
        return
    with REQ.open("a", encoding="utf-8") as f:
        f.write(package + "\n")
    print(f"✅ Added {package} to requirements.txt")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("package", help="Package spec (e.g. statsd==1.0.0 or statsd)")
    parser.add_argument("reason", help="Short reason / files / PR reference")
    parser.add_argument("--requirements", help="Also append to requirements.txt", action="store_true")

    args = parser.parse_args(argv)
    package = args.package.strip()
    version = ""
    if "==" in package:
        version = package.split("==", 1)[1]
    append_md(package, version, args.reason)
    if args.requirements:
        add_to_requirements(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
