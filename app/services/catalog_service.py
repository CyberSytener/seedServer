from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class CatalogError(ValueError):
    pass


class CatalogService:
    """Read-only access layer for the agent capability catalog."""

    def __init__(self, root: Optional[Path] = None) -> None:
        resolved = (root or self.default_root()).resolve()
        self._root = resolved

    @staticmethod
    def default_root() -> Path:
        return Path(__file__).resolve().parents[1] / "catalog"

    @property
    def root(self) -> Path:
        return self._root

    def load_tree(self) -> Dict[str, Any]:
        return self._load_json(self._root / "tree.json")

    def load_orchestration_policy(self) -> Dict[str, Any]:
        return self._load_json(self._root / "orchestration_policy_v0.json")

    def load_blueprint_patterns(self) -> Dict[str, Any]:
        return self._load_json(self._root / "blueprint_patterns_v0.json")

    def load_node(self, node_path: str) -> Dict[str, Any]:
        resolved = self.resolve_node(node_path)
        text = resolved.read_text(encoding="utf-8")
        if resolved.suffix.lower() == ".json":
            return {
                "path": resolved.relative_to(self._root).as_posix(),
                "content_type": "application/json",
                "content": json.loads(text),
            }
        return {
            "path": resolved.relative_to(self._root).as_posix(),
            "content_type": "text/markdown",
            "content": text,
        }

    def resolve_node(self, node_path: str) -> Path:
        raw = str(node_path or "").strip().replace("\\", "/")
        if not raw:
            raise CatalogError("catalog_path_empty")
        if raw.startswith("/") or raw.startswith("../") or raw.startswith("./"):
            raise CatalogError("catalog_path_not_relative")
        if ".." in raw.split("/"):
            raise CatalogError("catalog_path_traversal")
        if re.match(r"^[a-zA-Z]:", raw):
            raise CatalogError("catalog_path_absolute")

        candidate = (self._root / raw).resolve()
        root = self._root
        if candidate != root and root not in candidate.parents:
            raise CatalogError("catalog_path_outside_root")
        if candidate.suffix.lower() not in {".json", ".md"}:
            raise CatalogError("catalog_path_unsupported_extension")
        if not candidate.exists() or not candidate.is_file():
            raise FileNotFoundError(raw)
        return candidate

    def search(self, *, q: Optional[str], tag: Optional[str], limit: int = 40) -> List[Dict[str, Any]]:
        tree = self.load_tree()
        nodes = tree.get("nodes") if isinstance(tree.get("nodes"), list) else []
        q_norm = str(q or "").strip().lower()
        tag_norm = str(tag or "").strip().lower()
        results: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            tags = [str(item).strip().lower() for item in (node.get("tags") or []) if str(item).strip()]
            if tag_norm and tag_norm not in tags:
                continue
            if q_norm:
                haystack = " ".join(
                    [
                        str(node.get("id") or ""),
                        str(node.get("title") or ""),
                        str(node.get("path") or ""),
                        str(node.get("summary") or ""),
                        " ".join(tags),
                    ]
                ).lower()
                if q_norm not in haystack:
                    continue
            results.append(
                {
                    "id": node.get("id"),
                    "title": node.get("title"),
                    "kind": node.get("kind"),
                    "path": node.get("path"),
                    "tags": node.get("tags") if isinstance(node.get("tags"), list) else [],
                    "summary": node.get("summary"),
                }
            )
            if len(results) >= max(1, min(limit, 200)):
                break
        return results

    def list_module_summaries(self, *, limit: int = 16) -> List[Dict[str, Any]]:
        tree = self.load_tree()
        nodes = tree.get("nodes") if isinstance(tree.get("nodes"), list) else []
        modules: List[Dict[str, Any]] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if str(node.get("kind") or "") != "module":
                continue
            module_id = str(node.get("id") or "").replace("module:", "", 1)
            manifest = self.get_module_manifest(module_id)
            modules.append(
                {
                    "module_id": module_id,
                    "title": str(node.get("title") or module_id),
                    "summary": str(node.get("summary") or ""),
                    "stability": str(node.get("stability") or "stable"),
                    "risk_level": str(node.get("risk_level") or manifest.get("risk_level") or "low"),
                    "run_modes_supported": manifest.get("run_modes_supported")
                    if isinstance(manifest.get("run_modes_supported"), list)
                    else ["LIVE", "DRY_RUN"],
                    "cost_profile": manifest.get("cost_profile")
                    if isinstance(manifest.get("cost_profile"), dict)
                    else {},
                    "path": str(node.get("path") or ""),
                }
            )
            if len(modules) >= max(1, min(limit, 100)):
                break
        return modules

    def get_module_manifest(self, module_id: str) -> Dict[str, Any]:
        module_key = str(module_id or "").strip().lower()
        if not module_key:
            raise CatalogError("module_id_empty")
        path = self.resolve_node(f"modules/{module_key}.json")
        return self._load_json(path)

    def prompt_context_payload(self, *, domain: Optional[str] = None, max_modules: int = 12) -> Dict[str, Any]:
        dsl = self._load_json(self._root / "blueprint_dsl_v0.json")
        domain_pack = self._load_domain_pack(domain)
        policy = self.load_orchestration_policy()
        patterns = self.load_blueprint_patterns()
        modules = self.list_module_summaries(limit=max_modules)

        root_schema = dsl.get("root") if isinstance(dsl.get("root"), dict) else {}
        step_schema = {}
        defs = dsl.get("$defs") if isinstance(dsl.get("$defs"), dict) else {}
        if isinstance(defs.get("step"), dict):
            step_schema = defs["step"]

        return {
            "catalog_version": str(dsl.get("catalog_version") or "v0"),
            "dsl_summary": {
                "root_required": root_schema.get("required") if isinstance(root_schema.get("required"), list) else [],
                "step_required": step_schema.get("required") if isinstance(step_schema.get("required"), list) else [],
                "transforms": dsl.get("transforms") if isinstance(dsl.get("transforms"), list) else [],
            },
            "domain": domain_pack,
            "orchestration_policy": policy,
            "blueprint_patterns": patterns.get("patterns") if isinstance(patterns.get("patterns"), list) else [],
            "modules": modules,
            "retrieval_hints": {
                "tree_endpoint": "/v1/catalog/tree",
                "module_manifest_template": "/v1/catalog/node/modules/{module_id}.json",
                "domain_map_template": "/v1/catalog/node/domains/{domain}/domain_map_v0.json",
                "policy_endpoint": "/v1/catalog/node/orchestration_policy_v0.json",
                "patterns_endpoint": "/v1/catalog/node/blueprint_patterns_v0.json",
            },
        }

    def build_context_pack(
        self,
        *,
        domain: Optional[str],
        intent: Optional[str],
        constraints: Optional[Dict[str, Any]],
        max_modules: int = 12,
        include_manifests: bool = False,
    ) -> Dict[str, Any]:
        payload = self.prompt_context_payload(domain=domain, max_modules=max_modules)
        intent_norm = str(intent or "").strip().lower()
        constraints_map = constraints if isinstance(constraints, dict) else {}

        patterns = payload.get("blueprint_patterns") if isinstance(payload.get("blueprint_patterns"), list) else []
        matched_patterns: List[Dict[str, Any]] = []
        for pattern in patterns:
            if not isinstance(pattern, dict):
                continue
            tags = [str(item).strip().lower() for item in (pattern.get("intent_tags") or []) if str(item).strip()]
            if intent_norm:
                haystack = " ".join(tags + [str(pattern.get("pattern_id") or "")]).lower()
                if intent_norm not in haystack and not any(token in intent_norm for token in tags):
                    continue
            matched_patterns.append(pattern)
        if intent_norm and not matched_patterns:
            matched_patterns = patterns[:2]
        if not intent_norm:
            matched_patterns = patterns[:3]

        modules = payload.get("modules") if isinstance(payload.get("modules"), list) else []
        module_candidates: List[Dict[str, Any]] = []
        for module in modules:
            if not isinstance(module, dict):
                continue
            if not intent_norm:
                module_candidates.append(module)
                continue
            summary = str(module.get("summary") or "").lower()
            module_id = str(module.get("module_id") or "").lower()
            if intent_norm in summary or intent_norm in module_id:
                module_candidates.append(module)
                continue
            if any(tag in intent_norm for tag in [str(item).lower() for item in (module.get("run_modes_supported") or [])]):
                module_candidates.append(module)

        if not module_candidates:
            module_candidates = modules

        context_pack: Dict[str, Any] = {
            "catalog_version": payload.get("catalog_version", "v0"),
            "query": {
                "domain": domain,
                "intent": intent,
                "constraints": constraints_map,
                "max_modules": max_modules,
            },
            "dsl_summary": payload.get("dsl_summary") if isinstance(payload.get("dsl_summary"), dict) else {},
            "domain": payload.get("domain") if isinstance(payload.get("domain"), dict) else {},
            "policy": payload.get("orchestration_policy")
            if isinstance(payload.get("orchestration_policy"), dict)
            else {},
            "matched_patterns": matched_patterns[:4],
            "module_candidates": module_candidates[:max(1, min(max_modules, 50))],
            "retrieval_hints": payload.get("retrieval_hints") if isinstance(payload.get("retrieval_hints"), dict) else {},
        }

        if include_manifests:
            manifests: List[Dict[str, Any]] = []
            for module in context_pack["module_candidates"]:
                if not isinstance(module, dict):
                    continue
                module_id = str(module.get("module_id") or "").strip()
                if not module_id:
                    continue
                try:
                    manifests.append(self.get_module_manifest(module_id))
                except Exception:
                    continue
            context_pack["module_manifests"] = manifests
        return context_pack

    def render_prompt_context(self, *, domain: Optional[str] = None, max_modules: int = 12) -> str:
        payload = self.prompt_context_payload(domain=domain, max_modules=max_modules)
        lines: List[str] = []
        lines.append("CATALOG CONTEXT (v0)")
        dsl = payload.get("dsl_summary") if isinstance(payload.get("dsl_summary"), dict) else {}
        lines.append(
            "DSL required root keys: "
            + ", ".join(str(item) for item in (dsl.get("root_required") or []))
        )
        lines.append(
            "DSL required step keys: "
            + ", ".join(str(item) for item in (dsl.get("step_required") or []))
        )
        transforms = dsl.get("transforms") if isinstance(dsl.get("transforms"), list) else []
        transform_names: List[str] = []
        for item in transforms:
            if isinstance(item, str):
                transform_names.append(item)
            elif isinstance(item, dict):
                transform_names.append(str(item.get("name") or "transform"))
        if transform_names:
            lines.append("Supported transforms: " + ", ".join(transform_names[:12]))

        domain_payload = payload.get("domain")
        if isinstance(domain_payload, dict) and domain_payload:
            lines.append(
                "Domain pack: "
                + str(domain_payload.get("domain_id") or domain_payload.get("title") or "unknown")
            )
            summary = str(domain_payload.get("summary") or "").strip()
            if summary:
                lines.append("Domain summary: " + summary)

        lines.append("Modules available (id: summary):")
        for module in payload.get("modules") if isinstance(payload.get("modules"), list) else []:
            if not isinstance(module, dict):
                continue
            lines.append(
                f"- {module.get('module_id')}: {module.get('summary') or ''}".rstrip()
            )

        patterns = payload.get("blueprint_patterns") if isinstance(payload.get("blueprint_patterns"), list) else []
        if patterns:
            lines.append("Blueprint patterns:")
            for pattern in patterns[:3]:
                if not isinstance(pattern, dict):
                    continue
                lines.append(f"- {pattern.get('pattern_id')}: {pattern.get('description')}")

        hints = payload.get("retrieval_hints") if isinstance(payload.get("retrieval_hints"), dict) else {}
        lines.append("Retrieval hooks:")
        lines.append(f"- tree: {hints.get('tree_endpoint') or '/v1/catalog/tree'}")
        lines.append(
            "- module manifest by id: "
            + str(hints.get("module_manifest_template") or "/v1/catalog/node/modules/{module_id}.json")
        )
        if domain:
            lines.append(
                "- domain map: "
                + str(hints.get("domain_map_template") or "/v1/catalog/node/domains/{domain}/domain_map_v0.json")
            )

        return "\n".join(lines)

    def _load_domain_pack(self, domain: Optional[str]) -> Dict[str, Any]:
        domain_id = str(domain or "").strip().lower()
        if not domain_id:
            return {}
        path = self._root / "domains" / domain_id / "domain_map_v0.json"
        if not path.exists():
            return {}
        return self._load_json(path)

    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        raise CatalogError(f"invalid_catalog_json:{path}")
