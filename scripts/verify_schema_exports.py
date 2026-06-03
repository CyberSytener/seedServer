"""Verify realtime schema exports match legacy contracts names."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app.models.realtime as schema


EXPECTED_NAMES = {
    "ActionStatus",
    "ActionMetadata",
    "Action",
    "ClientMessage",
    "ClientCommand",
    "ClientActionConfirm",
    "ActionInvoke",
    "ActionConfirm",
    "ActionCancel",
    "SagaStatusRequest",
    "ClientMessageUnion",
    "ModelPartial",
    "ModelFinal",
    "ModelInvokeAction",
    "ActionResult",
    "SystemEvent",
    "SagaUpdate",
    "SagaStatusResponse",
    "ServerMessageUnion",
    "ConversationTurn",
    "STANDARD_ACTIONS",
}


def main() -> int:
    missing = sorted(name for name in EXPECTED_NAMES if not hasattr(schema, name))
    if missing:
        print("Missing exports from app.models.realtime:")
        for name in missing:
            print(f"- {name}")
        return 1

    print("Schema export verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

