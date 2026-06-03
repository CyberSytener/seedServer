"""Tests for app.services.catalog_service – CatalogService."""

import json
import pytest
from pathlib import Path

from app.services.catalog_service import CatalogError, CatalogService


# ---------------------------------------------------------------------------
# Fixtures – tiny filesystem tree
# ---------------------------------------------------------------------------

@pytest.fixture()
def catalog_dir(tmp_path: Path) -> Path:
    """Create a minimal catalog directory with required JSON/MD files."""
    root = tmp_path / "catalog"
    root.mkdir()

    # tree.json – two nodes (one module, one doc)
    tree = {
        "nodes": [
            {
                "id": "module:echo",
                "title": "Echo module",
                "kind": "module",
                "path": "modules/echo.json",
                "tags": ["test", "echo"],
                "summary": "Echoes input back",
                "stability": "stable",
                "risk_level": "low",
            },
            {
                "id": "doc:readme",
                "title": "Read Me",
                "kind": "doc",
                "path": "docs/readme.md",
                "tags": ["docs"],
                "summary": "Project readme",
            },
        ]
    }
    (root / "tree.json").write_text(json.dumps(tree), encoding="utf-8")

    # orchestration_policy_v0.json
    (root / "orchestration_policy_v0.json").write_text(
        json.dumps({"max_parallel": 4}), encoding="utf-8"
    )

    # blueprint_patterns_v0.json
    (root / "blueprint_patterns_v0.json").write_text(
        json.dumps({
            "patterns": [
                {
                    "pattern_id": "quick-echo",
                    "description": "Quick echo pattern",
                    "intent_tags": ["echo", "test"],
                },
            ]
        }),
        encoding="utf-8",
    )

    # blueprint_dsl_v0.json
    (root / "blueprint_dsl_v0.json").write_text(
        json.dumps({
            "catalog_version": "v0-test",
            "root": {"required": ["id", "steps"]},
            "$defs": {"step": {"required": ["action"]}},
            "transforms": ["resize", "crop"],
        }),
        encoding="utf-8",
    )

    # modules/echo.json
    modules = root / "modules"
    modules.mkdir()
    (modules / "echo.json").write_text(
        json.dumps({
            "module_id": "echo",
            "run_modes_supported": ["LIVE", "DRY_RUN"],
            "cost_profile": {"per_call_usd": 0.001},
            "risk_level": "low",
        }),
        encoding="utf-8",
    )

    # docs/readme.md
    docs = root / "docs"
    docs.mkdir()
    (docs / "readme.md").write_text("# Catalog Readme\nHello", encoding="utf-8")

    return root


@pytest.fixture()
def svc(catalog_dir: Path) -> CatalogService:
    return CatalogService(root=catalog_dir)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestCatalogServiceInit:
    def test_custom_root(self, catalog_dir: Path):
        svc = CatalogService(root=catalog_dir)
        assert svc.root == catalog_dir

    def test_default_root_is_path(self):
        r = CatalogService.default_root()
        assert isinstance(r, Path)


# ---------------------------------------------------------------------------
# load_tree / load_orchestration_policy / load_blueprint_patterns
# ---------------------------------------------------------------------------

class TestLoadTopLevelFiles:
    def test_load_tree(self, svc: CatalogService):
        tree = svc.load_tree()
        assert isinstance(tree, dict)
        assert len(tree["nodes"]) == 2

    def test_load_orchestration_policy(self, svc: CatalogService):
        policy = svc.load_orchestration_policy()
        assert policy["max_parallel"] == 4

    def test_load_blueprint_patterns(self, svc: CatalogService):
        patterns = svc.load_blueprint_patterns()
        assert "patterns" in patterns
        assert len(patterns["patterns"]) == 1


# ---------------------------------------------------------------------------
# resolve_node – path traversal guards
# ---------------------------------------------------------------------------

class TestResolveNode:
    def test_empty_path_raises(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_empty"):
            svc.resolve_node("")

    def test_absolute_slash(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_not_relative"):
            svc.resolve_node("/etc/passwd")

    def test_dotdot_prefix(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_not_relative"):
            svc.resolve_node("../secret.json")

    def test_dotslash_prefix(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_not_relative"):
            svc.resolve_node("./something.json")

    def test_double_dot_component(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_traversal"):
            svc.resolve_node("modules/../../../etc.json")

    def test_windows_drive_letter(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_absolute"):
            svc.resolve_node("C:\\Windows\\system32.json")

    def test_unsupported_extension(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="catalog_path_unsupported_extension"):
            svc.resolve_node("modules/echo.txt")

    def test_file_not_found(self, svc: CatalogService):
        with pytest.raises(FileNotFoundError):
            svc.resolve_node("modules/nonexistent.json")

    def test_valid_json(self, svc: CatalogService):
        result = svc.resolve_node("modules/echo.json")
        assert result.exists()

    def test_valid_md(self, svc: CatalogService):
        result = svc.resolve_node("docs/readme.md")
        assert result.exists()


# ---------------------------------------------------------------------------
# load_node
# ---------------------------------------------------------------------------

class TestLoadNode:
    def test_load_json_node(self, svc: CatalogService):
        node = svc.load_node("modules/echo.json")
        assert node["content_type"] == "application/json"
        assert node["content"]["module_id"] == "echo"

    def test_load_md_node(self, svc: CatalogService):
        node = svc.load_node("docs/readme.md")
        assert node["content_type"] == "text/markdown"
        assert "# Catalog Readme" in node["content"]


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_no_filters_returns_all(self, svc: CatalogService):
        results = svc.search(q=None, tag=None)
        assert len(results) == 2

    def test_query_filter(self, svc: CatalogService):
        results = svc.search(q="echo", tag=None)
        assert len(results) == 1
        assert results[0]["id"] == "module:echo"

    def test_tag_filter(self, svc: CatalogService):
        results = svc.search(q=None, tag="docs")
        assert len(results) == 1
        assert results[0]["id"] == "doc:readme"

    def test_combined_filter_no_match(self, svc: CatalogService):
        results = svc.search(q="nonexistent", tag="nope")
        assert results == []

    def test_limit(self, svc: CatalogService):
        results = svc.search(q=None, tag=None, limit=1)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# list_module_summaries / get_module_manifest
# ---------------------------------------------------------------------------

class TestModuleSummaries:
    def test_lists_modules(self, svc: CatalogService):
        modules = svc.list_module_summaries()
        assert len(modules) == 1
        assert modules[0]["module_id"] == "echo"
        assert modules[0]["risk_level"] == "low"

    def test_get_module_manifest(self, svc: CatalogService):
        manifest = svc.get_module_manifest("echo")
        assert manifest["module_id"] == "echo"

    def test_get_module_manifest_empty_id(self, svc: CatalogService):
        with pytest.raises(CatalogError, match="module_id_empty"):
            svc.get_module_manifest("")


# ---------------------------------------------------------------------------
# prompt_context_payload
# ---------------------------------------------------------------------------

class TestPromptContextPayload:
    def test_returns_expected_keys(self, svc: CatalogService):
        payload = svc.prompt_context_payload()
        assert payload["catalog_version"] == "v0-test"
        assert "dsl_summary" in payload
        assert "modules" in payload
        assert "retrieval_hints" in payload

    def test_dsl_summary_root_required(self, svc: CatalogService):
        payload = svc.prompt_context_payload()
        assert "id" in payload["dsl_summary"]["root_required"]


# ---------------------------------------------------------------------------
# build_context_pack
# ---------------------------------------------------------------------------

class TestBuildContextPack:
    def test_basic_pack(self, svc: CatalogService):
        pack = svc.build_context_pack(domain=None, intent=None, constraints=None)
        assert "module_candidates" in pack
        assert "matched_patterns" in pack

    def test_intent_filters_patterns(self, svc: CatalogService):
        pack = svc.build_context_pack(domain=None, intent="echo", constraints=None)
        assert len(pack["matched_patterns"]) >= 1

    def test_include_manifests(self, svc: CatalogService):
        pack = svc.build_context_pack(
            domain=None, intent=None, constraints=None, include_manifests=True
        )
        assert "module_manifests" in pack
        assert len(pack["module_manifests"]) >= 1


# ---------------------------------------------------------------------------
# render_prompt_context
# ---------------------------------------------------------------------------

class TestRenderPromptContext:
    def test_renders_string(self, svc: CatalogService):
        text = svc.render_prompt_context()
        assert isinstance(text, str)
        assert "CATALOG CONTEXT" in text
        assert "echo" in text


# ---------------------------------------------------------------------------
# _load_domain_pack
# ---------------------------------------------------------------------------

class TestLoadDomainPack:
    def test_empty_domain_returns_empty(self, svc: CatalogService):
        assert svc._load_domain_pack(None) == {}
        assert svc._load_domain_pack("") == {}

    def test_missing_domain_dir_returns_empty(self, svc: CatalogService):
        assert svc._load_domain_pack("no_such_domain") == {}

    def test_existing_domain(self, catalog_dir: Path):
        domain_dir = catalog_dir / "domains" / "food"
        domain_dir.mkdir(parents=True)
        (domain_dir / "domain_map_v0.json").write_text(
            json.dumps({"domain_id": "food", "title": "Food"}), encoding="utf-8"
        )
        svc = CatalogService(root=catalog_dir)
        pack = svc._load_domain_pack("food")
        assert pack["domain_id"] == "food"


# ---------------------------------------------------------------------------
# _load_json edge cases
# ---------------------------------------------------------------------------

class TestLoadJson:
    def test_non_dict_raises(self, catalog_dir: Path):
        bad = catalog_dir / "bad.json"
        bad.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        with pytest.raises(CatalogError, match="invalid_catalog_json"):
            CatalogService._load_json(bad)

    def test_valid_dict(self, catalog_dir: Path):
        good = catalog_dir / "good.json"
        good.write_text(json.dumps({"ok": True}), encoding="utf-8")
        result = CatalogService._load_json(good)
        assert result["ok"] is True
