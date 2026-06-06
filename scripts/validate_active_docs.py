from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTIVE_DOCS = [
    ROOT / "README.md",
    ROOT / "DEMO.md",
    ROOT / "SOURCE_OF_TRUTH.md",
    ROOT / "docs" / "ACTIVE_PLATFORM_SCOPE.md",
    ROOT / "docs" / "PHASE_0_STABILIZATION.md",
    ROOT / "docs" / "PLATFORM_ROADMAP.md",
    ROOT / "docs" / "PORTFOLIO_GITHUB_BRIEF.md",
    ROOT / "docs" / "PUBLISH_CHECKLIST.md",
    ROOT / "docs" / "TEST_STRATEGY.md",
    *sorted((ROOT / "docs" / "adr").glob("*.md")),
]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#]+)(?:#[^)]+)?\)")


def validate() -> list[str]:
    errors: list[str] = []
    for document in ACTIVE_DOCS:
        if not document.exists():
            errors.append(f"missing active document: {document.relative_to(ROOT)}")
            continue
        text = document.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            resolved = (document.parent / target).resolve()
            if not resolved.exists():
                errors.append(f"{document.relative_to(ROOT)} -> {target}")
    return errors


def main() -> int:
    errors = validate()
    if errors:
        print("Active documentation validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Active documentation validation passed ({len(ACTIVE_DOCS)} documents).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
