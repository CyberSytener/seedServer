from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.core.gemini_client import GeminiClient

logger = logging.getLogger(__name__)

# Blocks that are never allowed in user-generated blueprints
FORBIDDEN_BLOCKS: set[str] = set()

# Hard ceiling on steps per blueprint
MAX_STEPS = 10

# Domains that webhooks are allowed to target
ALLOWED_WEBHOOK_DOMAINS: set[str] = {"hooks.slack.com", "discord.com"}

# Private/reserved hostnames and IP ranges that must never be reached
_BLOCKED_WEBHOOK_HOSTS: tuple[str, ...] = (
    "localhost", "127.0.0.1", "0.0.0.0", "[::1]",
)
DEFAULT_INJECTION_MARKERS: tuple[str, ...] = (
    "ignore previous instructions",
    "system prompt",
    "developer instructions",
    "tool override",
    "bypass safety",
)
BLOCK_CAPABILITY_REQUIREMENTS: dict[str, set[str]] = {
    "notification_block": {"tool.notify"},
    "sub_saga": {"tool.orchestrate"},
    "admin_add_product": {"tool.admin"},
    "admin_update_product": {"tool.admin"},
    "admin_remove_product": {"tool.admin"},
    "billing_block": {"tool.billing"},
    "accounting_block": {"tool.billing"},
    "vision_apply_update": {"tool.vision.write"},
}


class SafetyVerdict:
    __slots__ = ("passed", "reason", "warnings")

    def __init__(self, passed: bool, reason: str = "", warnings: Optional[List[str]] = None) -> None:
        self.passed = passed
        self.reason = reason
        self.warnings = warnings or []

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "reason": self.reason, "warnings": self.warnings}


class SafetyValidator:
    def __init__(self, *, gemini_api_key: Optional[str] = None, gemini_model: Optional[str] = None) -> None:
        self._gemini_key = gemini_api_key or os.getenv("GEMINI_API_KEY")
        self._gemini_model = gemini_model or os.getenv("SEED_GEMINI_MODEL_FAST") or "gemini-2.0-flash-lite"
        self._gemini: Optional[GeminiClient] = None
        if self._gemini_key:
            try:
                self._gemini = GeminiClient(api_key=self._gemini_key, default_model=self._gemini_model)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Gemini client init failed for safety validator: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def validate(self, blueprint: Dict[str, Any]) -> SafetyVerdict:
        static = self._static_checks(blueprint)
        if not static.passed:
            return static

        ai = await self._ai_audit(blueprint)
        if not ai.passed:
            return ai

        # merge warnings
        return SafetyVerdict(passed=True, reason="ok", warnings=static.warnings + ai.warnings)

    # ------------------------------------------------------------------
    # Static rule checks
    # ------------------------------------------------------------------

    def _static_checks(self, blueprint: Dict[str, Any]) -> SafetyVerdict:
        steps = blueprint.get("steps") or []
        declared_capabilities = {
            str(cap).strip()
            for cap in (blueprint.get("capabilities") or [])
            if str(cap).strip()
        }
        warnings: List[str] = []

        if not steps:
            return SafetyVerdict(False, "Blueprint has no steps.")

        if len(steps) > MAX_STEPS:
            return SafetyVerdict(False, f"Too many steps ({len(steps)}). Maximum is {MAX_STEPS}.")

        seen_ids: set[str] = set()
        for idx, step in enumerate(steps):
            block = step.get("block") or step.get("block_type") or ""

            required_caps = BLOCK_CAPABILITY_REQUIREMENTS.get(block, set())
            missing_caps = sorted(required_caps - declared_capabilities)
            if missing_caps:
                return SafetyVerdict(
                    False,
                    f"step[{idx}] block '{block}' requires capabilities: {', '.join(missing_caps)}",
                )

            if block in FORBIDDEN_BLOCKS:
                return SafetyVerdict(False, f"step[{idx}] uses forbidden block type: {block}")

            step_id = step.get("id") or step.get("name") or ""
            if step_id in seen_ids:
                warnings.append(f"step[{idx}] duplicate id: {step_id}")
            seen_ids.add(step_id)

            params = step.get("params") or {}
            webhook = params.get("webhook_url") or ""
            if webhook:
                if not self._is_allowed_webhook(webhook):
                    return SafetyVerdict(
                        False,
                        f"step[{idx}] webhook URL not on allowlist: {webhook}",
                    )

            # Sub-saga recursion guard
            if block == "sub_saga":
                bp_name = (step.get("inputs") or {}).get("blueprint_name")
                own_name = blueprint.get("name") or ""
                if bp_name and bp_name == own_name:
                    return SafetyVerdict(False, f"step[{idx}] self-referencing sub_saga (infinite recursion).")

        control_payload = blueprint.get("control") if isinstance(blueprint.get("control"), dict) else {}
        data_payload = blueprint.get("data") if isinstance(blueprint.get("data"), dict) else {}
        if control_payload and data_payload:
            overlap = sorted(set(control_payload.keys()) & set(data_payload.keys()))
            if overlap:
                return SafetyVerdict(False, f"control/data separation violation: overlapping keys {', '.join(overlap)}")

        if self._contains_injection_marker(control_payload):
            return SafetyVerdict(False, "prompt-injection marker detected in control channel")

        return SafetyVerdict(True, "static_ok", warnings)

    @staticmethod
    def _contains_injection_marker(value: Any) -> bool:
        if isinstance(value, str):
            lowered = value.lower()
            return any(marker in lowered for marker in DEFAULT_INJECTION_MARKERS)
        if isinstance(value, dict):
            return any(SafetyValidator._contains_injection_marker(item) for item in value.values())
        if isinstance(value, list):
            return any(SafetyValidator._contains_injection_marker(item) for item in value)
        return False

    @staticmethod
    def _is_allowed_webhook(url: str) -> bool:
        if not url:
            return True
        try:
            from urllib.parse import urlparse
            import ipaddress
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if not host:
                return False
            # Block private/reserved hosts
            if host in _BLOCKED_WEBHOOK_HOSTS:
                return False
            # Block private IP addresses (SSRF protection)
            try:
                addr = ipaddress.ip_address(host)
                if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
                    return False
            except ValueError:
                pass  # Not an IP literal — check domain allowlist below
            return any(host.endswith(domain) for domain in ALLOWED_WEBHOOK_DOMAINS)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # AI audit
    # ------------------------------------------------------------------

    async def _ai_audit(self, blueprint: Dict[str, Any]) -> SafetyVerdict:
        if not self._gemini:
            logger.warning("No GEMINI_API_KEY configured — AI safety audit unavailable (fail-closed)")
            return SafetyVerdict(False, "ai_audit_unavailable (no key)")

        try:
            return await self._run_ai_audit(blueprint)
        except Exception as exc:
            logger.warning("AI safety audit failed (fail-closed): %s", exc)
            return SafetyVerdict(
                False,
                f"ai_audit_error ({exc})",
                warnings=["AI audit could not be completed — blueprint rejected"],
            )

    async def _run_ai_audit(self, blueprint: Dict[str, Any]) -> SafetyVerdict:
        prompt = (
            "You are a security auditor for automation workflows.\n"
            "Analyze the following saga blueprint JSON for:\n"
            "1. Security risks (data exfiltration, unauthorized access)\n"
            "2. Infinite loops or runaway recursion\n"
            "3. Community policy violations (spam, abuse)\n"
            "4. Resource abuse (excessive API calls)\n\n"
            f"Blueprint:\n```json\n{json.dumps(blueprint, indent=2)}\n```\n\n"
            "Respond in this exact JSON format (no markdown, no extra text):\n"
            '{"verdict": "PASS" or "FAIL", "reason": "short explanation", "warnings": ["optional list"]}'
        )

        if not self._gemini:
            raise RuntimeError("Gemini SDK is not available")
        text = await self._gemini.generate_content_async(prompt, model=self._gemini_model)
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        result = json.loads(text)
        verdict = str(result.get("verdict", "")).upper()
        reason = result.get("reason", "")
        warnings = result.get("warnings") or []

        if verdict == "FAIL":
            return SafetyVerdict(False, f"AI audit failed: {reason}", warnings)
        return SafetyVerdict(True, f"AI audit passed: {reason}", warnings)
