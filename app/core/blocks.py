from __future__ import annotations

import asyncio
import dataclasses
import logging
import smtplib
import uuid
from email.message import EmailMessage
from typing import Any, Dict, Iterable, Optional, Protocol, Type

import httpx

from app.infrastructure.db.pgvector_store import PgvectorStore
from app.services.job.scanner import JobScanner
from app.services.job.scorer import JobScorer
from app.services.job.sources import ArbetsformedlingenSource, RemotiveJobSource

logger = logging.getLogger(__name__)


class SagaBlock(Protocol):
    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Any: ...


@dataclasses.dataclass(frozen=True)
class BlockMetadata:
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    listing_id: Optional[str] = None  # marketplace listing ID, if sourced from marketplace


class BlockRegistry:
    def __init__(self):
        self._registry: Dict[str, Type[BlockBase]] = {}
        self._metadata: Dict[str, BlockMetadata] = {}

    def register(
        self,
        name: str,
        block_cls: Type[BlockBase],
        *,
        description: Optional[str] = None,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        listing_id: Optional[str] = None,
    ) -> None:
        self._registry[name] = block_cls
        self._metadata[name] = BlockMetadata(
            name=name,
            description=description or getattr(block_cls, "DESCRIPTION", ""),
            input_schema=input_schema or dict(getattr(block_cls, "INPUT_SCHEMA", {})),
            output_schema=output_schema or dict(getattr(block_cls, "OUTPUT_SCHEMA", {})),
            listing_id=listing_id,
        )

    def create(self, name: str, *, engine: Any, params: Optional[Dict[str, Any]] = None) -> BlockBase:
        block_cls = self._registry.get(name)
        if not block_cls:
            raise ValueError(f"Unknown block type: {name}")
        return block_cls(engine=engine, params=params or {})

    def list_blocks(self) -> list[str]:
        return sorted(self._registry.keys())

    def list_metadata(self) -> list[BlockMetadata]:
        return [self._metadata[name] for name in self.list_blocks() if name in self._metadata]

    def get_metadata(self, name: str) -> BlockMetadata:
        metadata = self._metadata.get(name)
        if not metadata:
            raise ValueError(f"Unknown block type: {name}")
        return metadata


_SHARED_REGISTRY: BlockRegistry | None = None


def _ensure_shared_registry() -> BlockRegistry:
    global _SHARED_REGISTRY
    if _SHARED_REGISTRY is None:
        registry = BlockRegistry()
        registry.register("market_scanner", MarketScannerBlock)
        registry.register("job_scorer", JobScorerBlock)
        registry.register("notification_block", NotificationBlock)
        registry.register("sub_saga", SubSagaBlock)

        # ── Control-flow blocks ──────────────────────────────────
        try:
            from app.core.control_flow_blocks import (
                FilterBlock,
                IfBlock,
                LoopBlock,
                MergeBlock,
                NoOpBlock,
                SetBlock,
                SwitchBlock,
                WaitBlock,
            )

            registry.register("if_block", IfBlock)
            registry.register("switch_block", SwitchBlock)
            registry.register("loop_block", LoopBlock)
            registry.register("merge_block", MergeBlock)
            registry.register("set_block", SetBlock)
            registry.register("filter_block", FilterBlock)
            registry.register("wait_block", WaitBlock)
            registry.register("noop_block", NoOpBlock)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Control-flow blocks registration failed: %s", exc)

        # ── Trigger blocks ───────────────────────────────────────
        try:
            from app.core.trigger_blocks import (
                CronTriggerBlock,
                ManualTriggerBlock,
                WebhookTriggerBlock,
            )

            registry.register("manual_trigger", ManualTriggerBlock)
            registry.register("webhook_trigger", WebhookTriggerBlock)
            registry.register("cron_trigger", CronTriggerBlock)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Trigger blocks registration failed: %s", exc)

        # ── NeoEats domain blocks ────────────────────────────────
        try:
            from app.core.neoeats_blocks import (
                AccountingBlock,
                AdminAddProductBlock,
                AdminRemoveProductBlock,
                AdminUpdateProductBlock,
                AlertBlock,
                BillingBlock,
                NeoEatsInputNormalizeBlock,
                NeoEatsInventoryGetBlock,
                NeoEatsInventoryNormalizeBlock,
                NeoEatsRecipeCompileStrictBlock,
                NeoEatsRecipeGenerateBlock,
                NeoEatsRecipeValidateBlock,
                DailyExpiryScanBlock,
                InventoryBlock,
                PriorityInventoryScanBlock,
                ReceiptProcessorBlock,
                ReceiptScannerBlock,
                SalesStatsFetchBlock,
                HotOfferGeneratorBlock,
                CulinaryValidatorBlock,
                ApprovalBlock,
                VisionAnalyzerBlock,
                VisionApplyUpdateBlock,
                VisionConfirmationBlock,
                VisionIntakeBlock,
            )

            registry.register("inventory_block", InventoryBlock)
            registry.register("priority_inventory_scan", PriorityInventoryScanBlock)
            registry.register("daily_expiry_scan", DailyExpiryScanBlock)
            registry.register("alert_block", AlertBlock)
            registry.register("billing_block", BillingBlock)
            registry.register("accounting_block", AccountingBlock)
            registry.register("admin_add_product", AdminAddProductBlock)
            registry.register("admin_update_product", AdminUpdateProductBlock)
            registry.register("admin_remove_product", AdminRemoveProductBlock)
            registry.register("receipt_scanner", ReceiptScannerBlock)
            registry.register("receipt_processor", ReceiptProcessorBlock)
            registry.register("sales_stats_fetch", SalesStatsFetchBlock)
            registry.register("hot_offer_generator", HotOfferGeneratorBlock)
            registry.register("culinary_validator", CulinaryValidatorBlock)
            registry.register("approval_block", ApprovalBlock)
            registry.register("vision_intake", VisionIntakeBlock)
            registry.register("vision_analyzer", VisionAnalyzerBlock)
            registry.register("vision_confirmation", VisionConfirmationBlock)
            registry.register("vision_apply_update", VisionApplyUpdateBlock)
            registry.register("neoeats.input.normalize", NeoEatsInputNormalizeBlock)
            registry.register("neoeats.inventory.get", NeoEatsInventoryGetBlock)
            registry.register("neoeats.inventory.normalize", NeoEatsInventoryNormalizeBlock)
            registry.register("neoeats.recipe.generate", NeoEatsRecipeGenerateBlock)
            registry.register("neoeats.recipe.compile_strict", NeoEatsRecipeCompileStrictBlock)
            registry.register("neoeats.recipe.validate", NeoEatsRecipeValidateBlock)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NeoEats blocks registration failed: %s", exc)
        try:
            from app.dynamic_registry import loader as registry_loader

            registry_loader.register_dynamic_blocks(registry, BlockBase)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Dynamic registry load failed: %s", exc)
        _SHARED_REGISTRY = registry
    return _SHARED_REGISTRY


class BlockBase:
    DESCRIPTION: str = ""
    INPUT_SCHEMA: Dict[str, Any] = {}
    OUTPUT_SCHEMA: Dict[str, Any] = {}

    def __init__(self, *, engine: Any, params: Dict[str, Any]):
        self._engine = engine
        self._params = params

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Any:
        raise NotImplementedError


class MarketScannerBlock(BlockBase):
    DESCRIPTION = "Scan job sources for a user persona and return matched jobs."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "User identifier."},
            "persona": {"type": "object", "description": "Persona and preferences."},
        },
        "required": ["user_id"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "scan_id": {"type": "string"},
            "jobs": {"type": "array", "items": {"type": "object"}},
            "source_counts": {"type": "object", "additionalProperties": {"type": "integer"}},
        },
        "required": ["scan_id", "jobs", "source_counts"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_id = inputs.get("user_id")
        persona = inputs.get("persona") or {}
        if not user_id:
            raise ValueError("MarketScannerBlock requires user_id")

        scanner = self._resolve_scanner()
        scan_result = await scanner.scan_for_user(user_id, persona)
        return {
            "scan_id": context.get("scan_id") or str(uuid.uuid4()),
            "jobs": scan_result.jobs,
            "source_counts": scan_result.source_counts,
        }

    def _resolve_scanner(self) -> JobScanner:
        adapters = getattr(self._engine, "adapters", {}) if self._engine else {}
        scanner = adapters.get("job_scanner")
        if scanner:
            return scanner
        return JobScanner(self._resolve_sources())

    def _resolve_sources(self) -> Iterable[object]:
        adapters = getattr(self._engine, "adapters", {}) if self._engine else {}
        sources = adapters.get("job_sources")
        if sources:
            return sources
        return [
            ArbetsformedlingenSource(),
            RemotiveJobSource(),
        ]

class JobScorerBlock(BlockBase):
    DESCRIPTION = "Score a list of jobs for a user persona and optionally persist the scores."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "User identifier."},
            "persona": {"type": "object", "description": "Persona and preferences."},
            "jobs": {"type": "array", "items": {"type": "object"}},
            "scan_id": {"type": "string", "description": "Existing scan id."},
            "persist": {"type": "boolean", "description": "Persist scores to storage."},
        },
        "required": ["user_id", "jobs"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "scored_count": {"type": "integer"},
            "scored_jobs": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["scored_count"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_id = inputs.get("user_id")
        persona = inputs.get("persona") or {}
        jobs = inputs.get("jobs") or []
        scan_id = inputs.get("scan_id") or context.get("scan_id")
        persist = bool(inputs.get("persist", True))

        # Dry-run override: never persist
        if self._params.get("_force_no_persist"):
            persist = False

        if not user_id:
            raise ValueError("JobScorerBlock requires user_id")
        if not jobs:
            return {"scored_count": 0}

        scorer = self._resolve_scorer()
        scored = await scorer.score_batch(
            user_id=user_id,
            jobs=list(jobs),
            persona=persona,
            scan_id=scan_id,
            persist=persist,
        )
        return {
            "scored_count": len(scored),
            "scored_jobs": scored,
        }

    def _resolve_scorer(self) -> JobScorer:
        adapters = getattr(self._engine, "adapters", {}) if self._engine else {}
        scorer = adapters.get("job_scorer")
        if scorer:
            return scorer
        vector_store = PgvectorStore(self._engine.db)
        return JobScorer(vector_store=vector_store, db=self._engine.db)


class NotificationBlock(BlockBase):
    DESCRIPTION = "Render and deliver a notification based on ranked items."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "Delivery channel: webhook, email, slack, telegram."},
            "message_body": {"type": "string", "description": "Optional prebuilt message."},
            "recipient_info": {"type": "object", "description": "Delivery metadata."},
            "items": {"type": "array", "items": {"type": "object"}},
            "timeout_sec": {"type": "number", "description": "Webhook timeout override."},
        },
        "required": ["items"],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "notified_count": {"type": "integer"},
            "notification_preview": {"type": "string"},
        },
        "required": ["notified_count"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        channel = inputs.get("channel") or self._params.get("channel")
        message_body = inputs.get("message_body")
        recipient_info = inputs.get("recipient_info") or self._params.get("recipient_info") or {}
        items = inputs.get("items") or []
        template = self._params.get("template")
        top_n = int(self._params.get("top_n") or 3)
        webhook_url = self._params.get("webhook_url") or recipient_info.get("webhook_url")
        timeout_sec = float(inputs.get("timeout_sec") or self._params.get("timeout_sec") or 5)

        normalized = [self._normalize_item(item) for item in items]
        ranked = self._sort_items(normalized)
        selected = ranked[:top_n]

        message = message_body or self._render_message(selected, template)
        if message:
            logger.info("\n%s\n%s\n%s\n%s\n%s", "=" * 42, "USER NOTIFICATION", message, recipient_info, "=" * 42)

        # Dry-run override: suppress real delivery
        if self._params.get("_suppress_webhook"):
            logger.info("[DRY_RUN] Notification delivery suppressed")
            return {
                "notified_count": len(selected),
                "notification_preview": message,
            }

        await self._deliver(
            channel=channel,
            message=message,
            recipient_info=recipient_info,
            webhook_url=webhook_url,
            timeout_sec=timeout_sec,
        )

        return {
            "notified_count": len(selected),
            "notification_preview": message,
        }

    async def _deliver(
        self,
        *,
        channel: str | None,
        message: str,
        recipient_info: Dict[str, Any],
        webhook_url: str | None,
        timeout_sec: float,
    ) -> None:
        if not message:
            return

        channel_value = (channel or recipient_info.get("channel") or "webhook").lower()
        if channel_value == "email":
            await self._send_email(message, recipient_info)
            return
        if channel_value == "slack":
            url = recipient_info.get("slack_webhook_url") or webhook_url
            if url:
                await self._send_webhook(url, message, timeout_sec)
            return
        if channel_value == "telegram":
            await self._send_telegram(message, recipient_info, timeout_sec)
            return

        if webhook_url:
            await self._send_webhook(webhook_url, message, timeout_sec)

    @staticmethod
    def _normalize_item(item: Any) -> Dict[str, Any]:
        if dataclasses.is_dataclass(item):
            return dataclasses.asdict(item)
        if isinstance(item, dict):
            return item
        return {"value": item}

    @staticmethod
    def _sort_items(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        def _score(item: Dict[str, Any]) -> float:
            scores = item.get("scores") or {}
            if isinstance(scores, dict):
                value = scores.get("composite")
                if isinstance(value, (int, float)):
                    return float(value)
            return 0.0

        return sorted(items, key=_score, reverse=True)

    @staticmethod
    def _render_message(items: list[Dict[str, Any]], template: Optional[str]) -> str:
        if not items:
            return ""
        line_template = template or "{title} at {company} ({location}) score={score}"
        lines: list[str] = []
        for item in items:
            scores = item.get("scores") or {}
            score = scores.get("composite") if isinstance(scores, dict) else None
            line = line_template.format_map(
                {
                    "title": item.get("title", ""),
                    "company": item.get("company", ""),
                    "location": item.get("location", ""),
                    "score": score if score is not None else "",
                    "url": item.get("url", ""),
                }
            )
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    async def _send_webhook(url: str, message: str, timeout_sec: float) -> None:
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                await client.post(url, json={"text": message})
        except httpx.RequestError as exc:
            logger.warning("Notification webhook failed: %s", exc)

    @staticmethod
    async def _send_email(message: str, recipient_info: Dict[str, Any]) -> None:
        smtp_host = recipient_info.get("smtp_host")
        smtp_port = int(recipient_info.get("smtp_port") or 587)
        smtp_user = recipient_info.get("smtp_user")
        smtp_pass = recipient_info.get("smtp_pass")
        smtp_from = recipient_info.get("email_from") or smtp_user
        smtp_to = recipient_info.get("email_to")
        if not (smtp_host and smtp_from and smtp_to):
            logger.warning("Email delivery skipped: missing smtp_host/email_from/email_to")
            return

        msg = EmailMessage()
        msg["Subject"] = recipient_info.get("subject") or "Saga Notification"
        msg["From"] = smtp_from
        msg["To"] = smtp_to
        msg.set_content(message)

        def _send() -> None:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if smtp_user and smtp_pass:
                    smtp.login(smtp_user, smtp_pass)
                smtp.send_message(msg)

        try:
            await asyncio.to_thread(_send)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Email delivery failed: %s", exc)

    @staticmethod
    async def _send_telegram(
        message: str,
        recipient_info: Dict[str, Any],
        timeout_sec: float,
    ) -> None:
        bot_token = recipient_info.get("telegram_bot_token")
        chat_id = recipient_info.get("telegram_chat_id")
        if not (bot_token and chat_id):
            logger.warning("Telegram delivery skipped: missing bot_token/chat_id")
            return
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        try:
            async with httpx.AsyncClient(timeout=timeout_sec) as client:
                await client.post(url, json=payload)
        except httpx.RequestError as exc:
            logger.warning("Telegram delivery failed: %s", exc)


class SubSagaBlock(BlockBase):
    DESCRIPTION = "Trigger another stored saga blueprint and return its results."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "blueprint_name": {"type": "string", "description": "Stored blueprint name."},
            "saga_name": {"type": "string", "description": "Alias for blueprint_name."},
            "payload": {"type": "object", "description": "Payload for the sub saga."},
            "inherit_context": {
                "type": "boolean",
                "description": "Merge current context into the sub saga payload.",
            },
        },
        "anyOf": [{"required": ["blueprint_name"]}, {"required": ["saga_name"]}],
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "sub_saga_status": {"type": "string"},
            "sub_saga_result": {"type": "object"},
        },
        "required": ["sub_saga_status"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        from app.core.saga_blueprints import blueprint_store
        from app.core.realtime.sagas.flows.dynamic_saga import DynamicSaga

        blueprint_name = (
            inputs.get("blueprint_name")
            or inputs.get("saga_name")
            or self._params.get("blueprint_name")
            or self._params.get("saga_name")
        )
        if not blueprint_name:
            raise ValueError("SubSagaBlock requires blueprint_name")

        stored = await blueprint_store.get(blueprint_name)
        if not stored:
            raise ValueError(f"SubSagaBlock blueprint not found: {blueprint_name}")

        inherit_context = bool(inputs.get("inherit_context", False))
        payload = dict(inputs.get("payload") or {})
        if inherit_context:
            payload = {**context, **payload}
        request_payload = payload.get("request")
        request_user_id = str(request_payload.get("user_id") or "").strip() if isinstance(request_payload, dict) else ""
        payload_user_id = str(payload.get("user_id") or "").strip()

        if request_user_id:
            payload["user_id"] = request_user_id
        elif payload_user_id:
            if isinstance(request_payload, dict):
                request_payload.setdefault("user_id", payload_user_id)
                payload["request"] = request_payload
        else:
            ctx_user_id = str(context.get("user_id") or "").strip()
            if not ctx_user_id and isinstance(context.get("request"), dict):
                ctx_user_id = str(context["request"].get("user_id") or "").strip()
            effective_user_id = ctx_user_id or "anonymous"
            payload["user_id"] = effective_user_id
            if isinstance(request_payload, dict):
                request_payload.setdefault("user_id", effective_user_id)
                payload["request"] = request_payload

        base_engine = getattr(self._engine, "_engine", self._engine)
        saga = DynamicSaga(engine=base_engine, blueprint=stored.get("steps", []), registry=build_default_registry())
        result = await saga.run(saga_id=str(uuid.uuid4()), payload=payload, steps=[])
        if isinstance(result, dict):
            return {
                "sub_saga_status": result.get("status", "unknown"),
                "sub_saga_result": result.get("result") if isinstance(result.get("result"), dict) else {},
            }
        return {"sub_saga_status": "unknown", "sub_saga_result": {}}


def build_default_registry() -> BlockRegistry:
    return _ensure_shared_registry()


def get_registry_schema() -> Dict[str, Any]:
    registry = build_default_registry()
    schema: Dict[str, Any] = {}
    react_flow_nodes: list[Dict[str, Any]] = []
    react_flow_edges: list[Dict[str, Any]] = []
    for index, metadata in enumerate(registry.list_metadata()):
        input_keys = sorted((metadata.input_schema.get("properties") or {}).keys())
        output_keys = sorted((metadata.output_schema.get("properties") or {}).keys())
        schema[metadata.name] = {
            "description": metadata.description,
            "inputs": dict(metadata.input_schema),
            "outputs": dict(metadata.output_schema),
        }
        react_flow_nodes.append(
            {
                "id": metadata.name,
                "type": "block",
                "position": {"x": 0, "y": index * 180},
                "data": {
                    "label": metadata.name,
                    "description": metadata.description,
                    "inputs": input_keys,
                    "outputs": output_keys,
                    "handles": {
                        "inputs": [{"id": f"in_{key}", "key": key, "type": "target"} for key in input_keys],
                        "outputs": [{"id": f"out_{key}", "key": key, "type": "source"} for key in output_keys],
                    },
                },
            }
        )
    return {"blocks": schema, "react_flow": {"nodes": react_flow_nodes, "edges": react_flow_edges}}
