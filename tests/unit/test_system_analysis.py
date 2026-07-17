from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ANALYZER_PATH = ROOT / "scripts" / "build_system_analysis.py"
SPEC = importlib.util.spec_from_file_location("seed_system_analysis", ANALYZER_PATH)
assert SPEC is not None and SPEC.loader is not None
ANALYZER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZER)


class SystemAnalysisTests(unittest.TestCase):
    def _profile(self) -> dict[str, object]:
        return {
            "schema_version": "1.0.0",
            "repository": "example/seed",
            "exclude_globs": [
                ".env",
                ".env.*",
                "*.db",
                "*.sqlite",
                "*.sqlite3",
                "*.log",
                "*.pem",
                "*.key",
                "*.p12",
                "*.zip",
            ],
            "required_docs": ["README.md"],
            "surfaces": [
                {
                    "id": "contracts",
                    "status": "candidate",
                    "description": "portable contracts",
                    "paths": ["app/contracts/**"],
                }
            ],
            "boundaries": [
                {
                    "id": "contracts-no-fastapi",
                    "severity": "error",
                    "source_paths": ["app/contracts/**"],
                    "forbidden_import_prefixes": ["fastapi", "app.infrastructure"],
                }
            ],
            "hotspot_thresholds": {
                "line_count": 30,
                "function_count": 5,
                "class_count": 5,
            },
        }

    def _write_repository(self, root: Path) -> None:
        (root / "app" / "contracts").mkdir(parents=True)
        (root / "app" / "api").mkdir(parents=True)
        (root / "scripts").mkdir(parents=True)
        (root / ".github" / "workflows").mkdir(parents=True)
        (root / "README.md").write_text("# Example\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            """
[project]
name = "example-seed"
version = "1.2.3"
requires-python = ">=3.11"
dependencies = ["fastapi==1.0.0"]

[project.optional-dependencies]
dev = ["pytest==9.0.0"]
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (root / "scripts" / "run_quality_gate.py").write_text(
            """
PORTFOLIO_TESTS = ["tests/unit/test_demo.py"]
GATE_CHOICES = ("portfolio", "integration")
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "tests.yml").write_text(
            "name: tests\non: [push]\n",
            encoding="utf-8",
        )
        (root / "app" / "contracts" / "models.py").write_text(
            """
import os
import fastapi
from pydantic import BaseModel

class ExampleModel(BaseModel):
    value: str

TOKEN_NAME = os.getenv("EXAMPLE_TOKEN")
""".strip()
            + "\n",
            encoding="utf-8",
        )
        (root / "app" / "api" / "routes.py").write_text(
            """
from fastapi import APIRouter

router = APIRouter()

@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
""".strip()
            + "\n",
            encoding="utf-8",
        )

    def test_inventory_detects_contracts_routes_environment_and_boundary_violations(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_repository(root)

            inventory = ANALYZER.build_inventory(root, self._profile(), revision="test-ref")

            self.assertEqual(inventory["revision"], "test-ref")
            self.assertEqual(inventory["summary"]["routes"], 1)
            self.assertEqual(inventory["python"]["routes"][0]["path"], "/health")
            self.assertIn(
                "EXAMPLE_TOKEN",
                {item["name"] for item in inventory["python"]["environment_references"]},
            )
            self.assertIn(
                "ExampleModel",
                {item["name"] for item in inventory["python"]["pydantic_models"]},
            )
            self.assertEqual(inventory["summary"]["boundary_violations"], 1)
            self.assertEqual(
                inventory["boundaries"]["violations"][0]["boundary_id"],
                "contracts-no-fastapi",
            )
            self.assertEqual(inventory["quality"]["gates"]["choices"], ["portfolio", "integration"])
            self.assertEqual(inventory["dependencies"]["project"]["version"], "1.2.3")

    def test_profile_excludes_sensitive_and_generated_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_repository(root)
            (root / ".env").write_text("SECRET=do-not-read\n", encoding="utf-8")
            (root / "local.sqlite3").write_bytes(b"not-a-real-database")
            (root / "node_modules" / "pkg").mkdir(parents=True)
            (root / "node_modules" / "pkg" / "index.js").write_text("secret", encoding="utf-8")
            (root / "system-analysis-artifacts").mkdir()
            (root / "system-analysis-artifacts" / "old.json").write_text("{}", encoding="utf-8")

            inventory = ANALYZER.build_inventory(root, self._profile(), revision="test-ref")
            paths = {
                item["path"]
                for item in ANALYZER.iter_repository_files(root, self._profile())
            }

            self.assertNotIn(".env", paths)
            self.assertNotIn("local.sqlite3", paths)
            self.assertNotIn("node_modules/pkg/index.js", paths)
            self.assertNotIn("system-analysis-artifacts/old.json", paths)
            serialized = json.dumps(inventory, sort_keys=True)
            self.assertNotIn("do-not-read", serialized)

    def test_inventory_and_written_artifacts_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "repo"
            output = Path(temporary_directory) / "output"
            root.mkdir()
            self._write_repository(root)

            first = ANALYZER.build_inventory(root, self._profile(), revision="same-ref")
            second = ANALYZER.build_inventory(root, self._profile(), revision="same-ref")
            self.assertEqual(first, second)

            json_path, markdown_path = ANALYZER.write_artifacts(first, output)
            loaded = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded, first)
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Seed System Analysis Inventory", markdown)
            self.assertIn("contracts-no-fastapi", markdown)

    def test_profile_loader_rejects_unknown_schema_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            profile_path = Path(temporary_directory) / "profile.json"
            profile_path.write_text(
                json.dumps({"schema_version": "9.9.9", "repository": "example/seed"}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "Unsupported analysis profile schema"):
                ANALYZER.load_profile(profile_path)


if __name__ == "__main__":
    unittest.main()
