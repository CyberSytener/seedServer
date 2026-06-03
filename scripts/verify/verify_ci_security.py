"""
Quick verification script for the current CI/security baseline.
"""
from __future__ import annotations

import sys
from pathlib import Path


def check_file_exists(filepath: str, description: str) -> bool:
    """Check if a file exists and print an ASCII-safe status line."""
    path = Path(filepath)
    exists = path.exists()
    status = "OK" if exists else "FAIL"
    print(f"{status} {description}: {filepath}")
    return exists


def main() -> int:
    """Verify all currently expected CI/security files are present."""
    print("=" * 70)
    print("CI/CD Security Baseline - Verification")
    print("=" * 70)
    print()

    all_present = True

    print("GitHub Actions Workflows:")
    for workflow, description in [
        (".github/workflows/security-gates.yml", "Security gates workflow"),
        (".github/workflows/smoke-tests.yml", "Smoke tests workflow"),
        (".github/workflows/full-tests.yml", "Full unit tests workflow"),
        (".github/workflows/integration-tests.yml", "Integration tests workflow"),
        (".github/workflows/lint.yml", "Lint workflow"),
        (".github/workflows/route-registration-sanity.yml", "Route registration sanity workflow"),
    ]:
        all_present &= check_file_exists(workflow, description)
    print()

    print("Security Configuration:")
    all_present &= check_file_exists(".pre-commit-config.yaml", "Pre-commit hooks")
    print()

    print("Documentation:")
    all_present &= check_file_exists("docs/guides/SECURITY.md", "Security policy")
    all_present &= check_file_exists("docs/guides/CI_SECURITY_GUIDE.md", "Implementation guide")
    all_present &= check_file_exists("docs/guides/CI_SECURITY_SUMMARY.md", "Implementation summary")
    print()

    print("Dependencies:")
    all_present &= check_file_exists("pyproject.toml", "Canonical package dependencies")
    all_present &= check_file_exists("requirements-dev.txt", "Legacy dev dependencies")
    print()

    print("=" * 70)
    if all_present:
        print("OK ALL CURRENT CI/SECURITY FILES PRESENT")
        print("=" * 70)
        print()
        print("Next Steps:")
        print("1. Install pre-commit: pip install pre-commit && pre-commit install")
        print("2. Push to GitHub to trigger workflows")
        print("3. Enable GitHub Security features in repository settings")
        print("4. Configure Dependabot alerts if dependency automation is desired")
        print("5. Review docs/guides/SECURITY.md and update contact info")
        print()
        print("Status: OK READY FOR CI VERIFICATION")
        return 0

    print("FAIL SOME FILES ARE MISSING")
    print("=" * 70)
    print()
    print("Please ensure all current CI/security files are present.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
