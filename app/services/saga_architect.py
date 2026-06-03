from __future__ import annotations

import json
import logging
import os
import re
import uuid
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from app.core.gemini_client import GeminiClient

from app.core.blocks import BlockRegistry, build_default_registry
from app.services.catalog_service import CatalogService
from app.services.inventory_provider import InventoryProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model-tier mapping: cheap → balanced → powerful
# ---------------------------------------------------------------------------
MODEL_TIERS: Dict[str, Dict[str, Any]] = {
    "cheap": {
        "model": os.getenv("SEED_GEMINI_MODEL_CHEAP") or "gemini-2.0-flash-lite",
        "label": "Gemini Flash-Lite",
        "credit_cost": 1,
    },
    "balanced": {
        "model": os.getenv("SEED_GEMINI_MODEL_BALANCED") or "gemini-2.0-flash",
        "label": "Gemini Flash",
        "credit_cost": 3,
    },
    "powerful": {
        "model": os.getenv("SEED_GEMINI_MODEL_POWERFUL") or "gemini-2.5-pro-preview-05-06",
        "label": "Gemini Pro",
        "credit_cost": 10,
    },
}

DEFAULT_TIER = "cheap"


def resolve_model_tier(tier: Optional[str] = None) -> Dict[str, Any]:
    """Return the tier config dict, falling back to DEFAULT_TIER."""
    return MODEL_TIERS.get((tier or "").lower(), MODEL_TIERS[DEFAULT_TIER])


def resolve_model_tier_name(tier: Optional[str] = None) -> str:
    candidate = (tier or "").lower()
    if candidate in MODEL_TIERS:
        return candidate
    return DEFAULT_TIER


class SagaArchitect:
    def __init__(
        self,
        registry: BlockRegistry | None = None,
        gemini_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        inventory_provider: Optional[InventoryProvider] = None,
        stock_provider: Optional[Callable[[], Awaitable[List[Dict[str, Any]]]]] = None,
        stock_snapshot: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self._registry = registry or build_default_registry()
        self._gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        self._gemini_model = gemini_model or os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-2.0-flash-lite"
        self._inventory_provider = inventory_provider
        self._stock_provider = stock_provider
        self._stock_snapshot: List[Dict[str, Any]] = list(stock_snapshot or [])
        self._gemini: Optional[GeminiClient] = None
        if self._gemini_key:
            try:
                self._gemini = GeminiClient(api_key=self._gemini_key, default_model=self._gemini_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for SagaArchitect: %s", exc)

    def generate_ai_context(self) -> str:
        payload = {
            "blocks": [
                {
                    "name": metadata.name,
                    "description": metadata.description,
                    "input_schema": metadata.input_schema,
                    "output_schema": metadata.output_schema,
                }
                for metadata in self._registry.list_metadata()
            ]
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    def generate_prompt_context(
        self,
        stock_snapshot: Optional[List[Dict[str, Any]]] = None,
        *,
        domain: Optional[str] = None,
    ) -> str:
        lines: List[str] = []
        snapshot = stock_snapshot if stock_snapshot is not None else self._stock_snapshot
        lines.append("SYSTEM CONTEXT: Agent Capability Catalog")
        lines.append("Use this to build a valid saga blueprint JSON.")
        lines.append("")
        try:
            catalog = CatalogService()
            lines.append(catalog.render_prompt_context(domain=domain, max_modules=14))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Catalog context unavailable, fallback to registry context: %s", exc)
            lines.append("CATALOG FALLBACK: dynamic registry metadata")
            for metadata in self._registry.list_metadata():
                input_keys = self._schema_keys(metadata.input_schema)
                output_keys = self._schema_keys(metadata.output_schema)
                lines.append(f"- {metadata.name}")
                lines.append(f"  inputs: {', '.join(input_keys) if input_keys else 'none'}")
                lines.append(f"  outputs: {', '.join(output_keys) if output_keys else 'none'}")

        lines.append("")
        lines.append("INPUT MAPPING:")
        lines.append("- You can map inputs from context using { 'from': 'step_id.key' }.")
        lines.append("- Allowed roots: payload, request, user_id, persona, scan_id, or a prior step id.")
        lines.append("- Example: { 'from': 'scan_jobs.jobs' } maps output from step id scan_jobs.")
        lines.append("- You may add { 'default': <value> } to use when the source is missing.")

        lines.append("")
        lines.append("TRANSFORMS:")
        lines.append("- Add { 'transform': 'lower' } or { 'transform': { 'name': 'lower' } }.")
        lines.append("- Supported: lower, upper, strip, join, split, to_bool, to_int, to_float, coalesce, len, slice.")
        lines.append("- join: { 'name': 'join', 'sep': ' ' }, split: { 'name': 'split', 'sep': ' ' }.")
        lines.append("- coalesce: { 'name': 'coalesce', 'fallback': <value> }.")
        lines.append("- slice: { 'name': 'slice', 'start': 0, 'end': 5 }.")

        lines.append("")
        lines.append("OUTPUT EXPECTATION:")
        lines.append("- Return only a JSON blueprint (no prose) when asked to generate a saga.")

        if snapshot:
            inventory_lines = self._format_inventory_snapshot(snapshot)
            if inventory_lines:
                lines.append("")
                lines.append("INVENTORY CONSTRAINTS:")
                lines.extend(inventory_lines)
                lines.append("- Only propose ingredients listed as in stock.")
                lines.append("- If a requested ingredient is out of stock, substitute with an in-stock option.")

        return "\n".join(lines)

    async def draft_blueprint(
        self,
        prompt: str,
        *,
        model_tier: Optional[str] = None,
        stock_snapshot: Optional[List[Dict[str, Any]]] = None,
        domain: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return (blueprint, generation_meta) where meta contains model info."""
        effective_tier = resolve_model_tier_name(model_tier)
        tier_cfg = resolve_model_tier(effective_tier)
        meta: Dict[str, Any] = {
            "model_tier": effective_tier,
            "model_name": tier_cfg["model"],
            "model_label": tier_cfg["label"],
            "credit_cost": tier_cfg["credit_cost"],
            "provider_request_id": None,
            "usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
            "cost": None,
        }
        try:
            if not self._gemini_key:
                logger.warning("No GEMINI_API_KEY set; using mock draft")
                meta["model_name"] = "mock"
                meta["model_label"] = "Mock (no API key)"
                meta["credit_cost"] = 0
                return self._draft_blueprint_mock(prompt), meta
            snapshot = await self._get_stock_snapshot(stock_snapshot)
            filtered_prompt = self._apply_stock_filter(prompt, snapshot)
            bp, provider_meta = await self._draft_blueprint_llm(
                filtered_prompt,
                model_name=tier_cfg["model"],
                stock_snapshot=snapshot,
                domain=domain,
            )
            if isinstance(provider_meta, dict):
                meta["provider_request_id"] = provider_meta.get("provider_request_id")
                usage = provider_meta.get("usage")
                if isinstance(usage, dict):
                    meta["usage"] = {
                        "input_tokens": usage.get("input_tokens"),
                        "output_tokens": usage.get("output_tokens"),
                        "total_tokens": usage.get("total_tokens"),
                    }
                meta["cost"] = provider_meta.get("cost")
            return bp, meta
        except Exception as e:
            logger.warning(f"LLM draft failed: {e}; falling back to mock")
            meta["model_name"] = "mock_fallback"
            meta["model_label"] = "Mock (fallback)"
            meta["credit_cost"] = 0
            return self._draft_blueprint_mock(prompt), meta

    async def draft_block_code(
        self, prompt: str, *, model_tier: Optional[str] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        effective_tier = resolve_model_tier_name(model_tier)
        tier_cfg = resolve_model_tier(effective_tier)
        meta: Dict[str, Any] = {
            "model_tier": effective_tier,
            "model_name": tier_cfg["model"],
            "model_label": tier_cfg["label"],
            "credit_cost": tier_cfg["credit_cost"],
        }
        try:
            if not self._gemini_key:
                logger.warning("No GEMINI_API_KEY set; using mock block draft")
                meta["model_name"] = "mock"
                meta["model_label"] = "Mock (no API key)"
                meta["credit_cost"] = 0
                return self._draft_block_mock(prompt), meta
            code = await self._draft_block_llm(prompt, model_name=tier_cfg["model"])
            return code, meta
        except Exception as exc:
            logger.warning("LLM block draft failed: %s; falling back to mock", exc)
            meta["model_name"] = "mock_fallback"
            meta["model_label"] = "Mock (fallback)"
            meta["credit_cost"] = 0
            return self._draft_block_mock(prompt), meta

    async def _draft_blueprint_llm(
        self,
        prompt: str,
        *,
        model_name: Optional[str] = None,
        stock_snapshot: Optional[List[Dict[str, Any]]] = None,
        domain: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        system_context = self.generate_prompt_context(stock_snapshot, domain=domain)
        message = f"{system_context}\n\nUSER REQUEST: {prompt}\n\nReturn ONLY a valid JSON blueprint, no other text."
        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
        text, provider_meta = await self._gemini.generate_content_async_with_meta(
            message,
            model=model_name or self._gemini_model,
        )
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        blueprint = json.loads(text)
        if not isinstance(provider_meta, dict):
            provider_meta = {}
        return blueprint, provider_meta

    async def _draft_block_llm(
        self, prompt: str, *, model_name: Optional[str] = None,
    ) -> str:
        block_contract = (
            "Write a single Python class that inherits BlockBase and implements: "
            "DESCRIPTION, INPUT_SCHEMA, OUTPUT_SCHEMA, and async execute(self, context, inputs). "
            "BlockBase is already in scope; do not import it. "
            "Avoid side effects and avoid external imports. Use only standard library types."
        )
        message = (
            "SYSTEM CONTEXT: Saga Block Contract\n"
            f"{block_contract}\n\n"
            "Return ONLY Python code, no markdown or prose.\n\n"
            f"USER REQUEST: {prompt}"
        )
        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
        text = await self._gemini.generate_content_async(
            message,
            model=model_name or self._gemini_model,
        )
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
        return text.strip()

    def _draft_blueprint_mock(self, prompt: str) -> Dict[str, Any]:
        name = self._draft_name(prompt)
        lowered = (prompt or "").lower()

        if "meta" in lowered or "sub" in lowered or "nested" in lowered:
            return self._draft_meta_test(name)
        if "silent" in lowered or "audit" in lowered:
            return self._draft_silent_audit(name)
        return self._draft_standard_job_alert(name)

    def _draft_block_mock(self, prompt: str) -> str:
        block_name = "CustomBlock"
        return (
            "class CustomBlock(BlockBase):\n"
            "    DESCRIPTION = 'Example dynamic block'\n"
            "    INPUT_SCHEMA = {\n"
            "        'type': 'object',\n"
            "        'properties': {'value': {'type': 'string'}},\n"
            "        'required': ['value'],\n"
            "    }\n"
            "    OUTPUT_SCHEMA = {\n"
            "        'type': 'object',\n"
            "        'properties': {'echo': {'type': 'string'}},\n"
            "        'required': ['echo'],\n"
            "    }\n"
            "\n"
            "    async def execute(self, context, inputs):\n"
            "        return {'echo': inputs.get('value', '')}\n"
        )

    async def _get_stock_snapshot(
        self,
        override: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        if override is not None:
            return list(override)
        if self._stock_snapshot:
            return list(self._stock_snapshot)
        if self._inventory_provider:
            try:
                snapshot = await self._inventory_provider.list_stock_snapshot()
                self._stock_snapshot = list(snapshot or [])
                return list(self._stock_snapshot)
            except Exception as exc:
                logger.warning("Failed to load inventory snapshot: %s", exc)
        if self._stock_provider:
            try:
                snapshot = await self._stock_provider()
                self._stock_snapshot = list(snapshot or [])
                return list(self._stock_snapshot)
            except Exception as exc:
                logger.warning("Failed to load stock snapshot: %s", exc)
        return []

    @staticmethod
    def _format_inventory_snapshot(snapshot: List[Dict[str, Any]]) -> List[str]:
        lines: List[str] = []
        for item in snapshot:
            name = str(item.get("ingredient_name") or item.get("name") or "").strip()
            if not name:
                continue
            quantity = item.get("quantity")
            unit = item.get("unit") or ""
            status = "in_stock" if _is_in_stock(quantity) else "out_of_stock"
            qty_label = f"{quantity} {unit}".strip() if quantity is not None else "unknown"
            lines.append(f"- {name}: {qty_label} ({status})")
        return lines

    @staticmethod
    def _apply_stock_filter(prompt: str, snapshot: List[Dict[str, Any]]) -> str:
        if not prompt or not snapshot:
            return prompt

        in_stock: List[str] = []
        out_of_stock: List[str] = []
        for item in snapshot:
            name = str(item.get("ingredient_name") or item.get("name") or "").strip()
            if not name:
                continue
            if _is_in_stock(item.get("quantity")):
                in_stock.append(name)
            else:
                out_of_stock.append(name)

        filtered = prompt
        for name in out_of_stock:
            if not name:
                continue
            pattern = r"\b" + re.escape(name) + r"\b"
            filtered = re.sub(pattern, "", filtered, flags=re.IGNORECASE)

        if in_stock:
            filtered = (
                f"{filtered}\n\n"
                "Inventory constraint: use only these ingredients: "
                f"{', '.join(sorted(set(in_stock)))}."
            )
        return filtered.strip()

    def validate_blueprint(self, json_data: Dict[str, Any] | List[Dict[str, Any]]) -> Dict[str, Any]:
        steps = self._normalize_steps(json_data)
        errors: List[str] = []
        step_names: List[str] = []
        block_sequence: List[str] = []

        for index, step in enumerate(steps):
            name = step.get("name") or step.get("id")
            block_type = step.get("block") or step.get("block_type")
            block_sequence.append(str(block_type or ""))

            if not name:
                errors.append(f"step[{index}] is missing name/id")
                name = f"step_{index}"
            if name in step_names:
                errors.append(f"duplicate step name: {name}")
            step_names.append(name)

            if not block_type:
                errors.append(f"step[{index}] ({name}) missing block type")
            elif block_type not in self._registry.list_blocks():
                errors.append(f"step[{index}] ({name}) unknown block type: {block_type}")

            inputs = step.get("inputs") or {}
            errors.extend(self._validate_required_inputs(block_type, name, inputs))

            for ref in self._iter_from_refs(inputs):
                errors.extend(self._validate_reference(ref, name, step_names))

        errors.extend(self._validate_neoeats_rules(json_data, steps, block_sequence))

        return {"ok": len(errors) == 0, "errors": errors}

    @staticmethod
    def _is_order_saga(json_data: Dict[str, Any] | List[Dict[str, Any]], block_sequence: List[str]) -> bool:
        if isinstance(json_data, dict):
            name = str(json_data.get("name") or "").lower()
            if any(token in name for token in ("order", "checkout", "purchase")):
                return True
        return any(
            block in block_sequence
            for block in ("inventory_block", "billing_block", "accounting_block")
        )

    @staticmethod
    def _first_index(block_sequence: List[str], block_name: str) -> Optional[int]:
        try:
            return block_sequence.index(block_name)
        except ValueError:
            return None

    def _validate_neoeats_rules(
        self,
        json_data: Dict[str, Any] | List[Dict[str, Any]],
        steps: List[Dict[str, Any]],
        block_sequence: List[str],
    ) -> List[str]:
        errors: List[str] = []
        if not steps:
            return errors

        if self._is_order_saga(json_data, block_sequence):
            required = ["inventory_block", "billing_block", "accounting_block"]
            missing = [block for block in required if block not in block_sequence]
            if missing:
                errors.append(
                    "order saga missing required blocks: " + ", ".join(missing)
                )

            order = [
                self._first_index(block_sequence, "inventory_block"),
                self._first_index(block_sequence, "billing_block"),
                self._first_index(block_sequence, "accounting_block"),
            ]
            if all(index is not None for index in order):
                if not (order[0] < order[1] < order[2]):
                    errors.append(
                        "order saga blocks must be ordered: inventory_block -> billing_block -> accounting_block"
                    )

        if "daily_expiry_scan" in block_sequence:
            if "alert_block" not in block_sequence and "notification_block" not in block_sequence:
                errors.append("daily expiry saga requires alert_block or notification_block")
            scan_index = self._first_index(block_sequence, "daily_expiry_scan")
            alert_index = self._first_index(block_sequence, "alert_block")
            if scan_index is not None and alert_index is not None and scan_index > alert_index:
                errors.append("daily_expiry_scan must occur before alert_block")

        hot_offer_blocks = {
            "priority_inventory_scan",
            "sales_stats_fetch",
            "hot_offer_generator",
            "culinary_validator",
            "approval_block",
        }
        name_hint = ""
        if isinstance(json_data, dict):
            name_hint = str(json_data.get("name") or "").lower()
        if hot_offer_blocks.intersection(block_sequence) or "hot_offer" in name_hint:
            required = [
                "priority_inventory_scan",
                "sales_stats_fetch",
                "hot_offer_generator",
                "culinary_validator",
                "approval_block",
            ]
            missing = [block for block in required if block not in block_sequence]
            if missing:
                errors.append("hot offer saga missing required blocks: " + ", ".join(missing))

            order = [self._first_index(block_sequence, block) for block in required]
            if all(index is not None for index in order):
                if not all(order[i] < order[i + 1] for i in range(len(order) - 1)):
                    errors.append(
                        "hot offer saga blocks must be ordered: "
                        "priority_inventory_scan -> sales_stats_fetch -> "
                        "hot_offer_generator -> culinary_validator -> approval_block"
                    )

        return errors

    @staticmethod
    def _normalize_steps(json_data: Dict[str, Any] | List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if isinstance(json_data, list):
            return json_data
        return list(json_data.get("steps") or [])

    def _validate_required_inputs(self, block_type: str | None, step_name: str, inputs: Dict[str, Any]) -> List[str]:
        if not block_type or block_type not in self._registry.list_blocks():
            return []
        schema = self._registry.get_metadata(block_type).input_schema
        required: Iterable[str] = schema.get("required") or []
        missing = [field for field in required if field not in inputs]
        if missing:
            return [f"step[{step_name}] missing required inputs: {', '.join(missing)}"]

        any_of = schema.get("anyOf") or []
        if any_of:
            satisfied = False
            for option in any_of:
                option_required = option.get("required") or []
                if all(field in inputs for field in option_required):
                    satisfied = True
                    break
            if not satisfied:
                return [f"step[{step_name}] missing one of the required input sets"]
        return []

    @staticmethod
    def _schema_keys(schema: Dict[str, Any]) -> List[str]:
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if isinstance(properties, dict):
            return sorted(properties.keys())
        return []

    @staticmethod
    def _draft_name(prompt: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "_", (prompt or "").lower()).strip("_")
        if not base:
            base = "draft"
        return f"{base}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _draft_standard_job_alert(name: str) -> Dict[str, Any]:
        return {
            "name": name,
            "version": "v1",
            "steps": [
                {
                    "id": "scan_jobs",
                    "block": "market_scanner",
                    "inputs": {
                        "user_id": {"from": "user_id"},
                        "persona": {"from": "persona"},
                    },
                },
                {
                    "id": "score_jobs",
                    "block": "job_scorer",
                    "inputs": {
                        "user_id": {"from": "user_id"},
                        "persona": {"from": "persona"},
                        "jobs": {"from": "scan_jobs.jobs"},
                        "scan_id": {"from": "scan_jobs.scan_id"},
                        "persist": True,
                    },
                },
                {
                    "id": "notify_user",
                    "block": "notification_block",
                    "inputs": {
                        "items": {"from": "score_jobs.scored_jobs"},
                        "message_body": {"from": "request.message_body", "default": ""},
                        "recipient_info": {"from": "request.recipient_info", "default": {}},
                    },
                    "params": {
                        "top_n": 3,
                    },
                },
            ],
        }

    @staticmethod
    def _draft_silent_audit(name: str) -> Dict[str, Any]:
        return {
            "name": name,
            "version": "v1",
            "steps": [
                {
                    "id": "scan_jobs",
                    "block": "market_scanner",
                    "inputs": {
                        "user_id": {"from": "user_id"},
                        "persona": {"from": "persona"},
                    },
                },
                {
                    "id": "score_jobs",
                    "block": "job_scorer",
                    "inputs": {
                        "user_id": {"from": "user_id"},
                        "persona": {"from": "persona"},
                        "jobs": {"from": "scan_jobs.jobs"},
                        "scan_id": {"from": "scan_jobs.scan_id"},
                        "persist": True,
                    },
                },
            ],
        }

    @staticmethod
    def _draft_meta_test(name: str) -> Dict[str, Any]:
        return {
            "name": name,
            "version": "v1",
            "steps": [
                {
                    "id": "run_child",
                    "block": "sub_saga",
                    "inputs": {
                        "blueprint_name": "standard_job_alert",
                        "payload": {
                            "user_id": {"from": "user_id"},
                            "persona": {"from": "persona"},
                            "message_body": {"from": "request.message_body", "default": ""},
                            "recipient_info": {"from": "request.recipient_info", "default": {}},
                        },
                    },
                }
            ],
        }

    @staticmethod
    def _iter_from_refs(value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            if "from" in value and isinstance(value.get("from"), (str, list, tuple)):
                yield value.get("from")
            for item in value.values():
                yield from SagaArchitect._iter_from_refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from SagaArchitect._iter_from_refs(item)

    @staticmethod
    def _normalize_path(ref: Any) -> List[str]:
        if isinstance(ref, str):
            return [part for part in ref.split(".") if part]
        if isinstance(ref, (list, tuple)):
            return [str(part) for part in ref if part]
        return []

    @staticmethod
    def _validate_reference(ref: Any, step_name: str, step_names: List[str]) -> List[str]:
        parts = SagaArchitect._normalize_path(ref)
        if not parts:
            return []

        root = parts[0]
        allowed_roots = {"payload", "request", "user_id", "persona", "scan_id"}
        if root in allowed_roots:
            return []

        if root not in step_names:
            return [f"step[{step_name}] reference to unknown step: {root}"]

        if step_names.index(root) >= step_names.index(step_name):
            return [f"step[{step_name}] reference to future step: {root}"]

        return []


def _is_in_stock(quantity: Any) -> bool:
    if quantity is None:
        return False
    try:
        return float(quantity) > 0
    except (TypeError, ValueError):
        return False
