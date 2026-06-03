"""Trigger blocks for n8n-style automation pipelines.

Trigger blocks serve as entry points to a flow.  They capture and
validate incoming data (manual, webhook, or schedule metadata) and
pass it through to downstream nodes.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from app.core.blocks import BlockBase

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Manual Trigger — user-initiated flow start
# ------------------------------------------------------------------

class ManualTriggerBlock(BlockBase):
    """Entry point triggered by a user pressing 'Run'.

    Passes the incoming payload through unchanged, adding trigger metadata.
    """

    DESCRIPTION = "Manual trigger: starts the flow when a user presses Run."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "payload": {"type": "object", "description": "Custom input data."},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "_trigger": {"type": "string", "const": "manual"},
            "triggered_at": {"type": "number"},
            "data": {"type": "object"},
        },
        "required": ["_trigger", "triggered_at"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        data = inputs.get("payload") or inputs
        return {
            "_trigger": "manual",
            "triggered_at": time.time(),
            "data": data,
        }


# ------------------------------------------------------------------
# Webhook Trigger — HTTP-initiated flow start
# ------------------------------------------------------------------

class WebhookTriggerBlock(BlockBase):
    """Entry point for flows triggered by an incoming HTTP webhook.

    Validates and normalizes the webhook payload.
    """

    DESCRIPTION = "Webhook trigger: starts the flow from an incoming HTTP request."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "description": "HTTP method (GET, POST, etc.)."},
            "headers": {"type": "object", "description": "Request headers."},
            "body": {"type": "object", "description": "Request body."},
            "query_params": {"type": "object", "description": "URL query parameters."},
            "auth_token": {"type": "string", "description": "Optional auth token to validate."},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "_trigger": {"type": "string", "const": "webhook"},
            "triggered_at": {"type": "number"},
            "method": {"type": "string"},
            "headers": {"type": "object"},
            "body": {"type": "object"},
            "query_params": {"type": "object"},
        },
        "required": ["_trigger", "triggered_at", "body"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        expected_token = self._params.get("auth_token")
        if expected_token:
            provided = inputs.get("auth_token") or ""
            if provided != expected_token:
                raise PermissionError("Webhook auth token mismatch")

        return {
            "_trigger": "webhook",
            "triggered_at": time.time(),
            "method": inputs.get("method", "POST"),
            "headers": inputs.get("headers") or {},
            "body": inputs.get("body") or {},
            "query_params": inputs.get("query_params") or {},
        }


# ------------------------------------------------------------------
# Cron / Schedule Trigger
# ------------------------------------------------------------------

class CronTriggerBlock(BlockBase):
    """Entry point for scheduled/cron-triggered flows.

    The actual scheduling is managed externally (e.g. APScheduler, systemd,
    or a scheduler service).  This block captures schedule metadata and
    passes it downstream.
    """

    DESCRIPTION = "Schedule trigger: starts the flow on a cron/interval schedule."
    INPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "cron_expression": {"type": "string", "description": "Cron expression (e.g. '0 */6 * * *')."},
            "timezone": {"type": "string", "description": "IANA timezone (default: UTC)."},
            "payload": {"type": "object", "description": "Static payload for each run."},
        },
    }
    OUTPUT_SCHEMA = {
        "type": "object",
        "properties": {
            "_trigger": {"type": "string", "const": "cron"},
            "triggered_at": {"type": "number"},
            "cron_expression": {"type": "string"},
            "timezone": {"type": "string"},
            "data": {"type": "object"},
        },
        "required": ["_trigger", "triggered_at"],
    }

    async def execute(self, context: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
        cron_expr = inputs.get("cron_expression") or self._params.get("cron_expression") or "* * * * *"
        timezone = inputs.get("timezone") or self._params.get("timezone") or "UTC"
        data = inputs.get("payload") or self._params.get("payload") or {}

        return {
            "_trigger": "cron",
            "triggered_at": time.time(),
            "cron_expression": cron_expr,
            "timezone": timezone,
            "data": data,
        }
