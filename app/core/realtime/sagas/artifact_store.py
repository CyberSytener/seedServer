from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


class ArtifactStore:
    """Lightweight local artifact store with hash-addressed references."""

    def __init__(self, *, base_dir: str | None = None) -> None:
        target_dir = base_dir or os.getenv("SEED_ARTIFACT_STORE_DIR") or "/tmp/seed_artifacts"
        self._base = Path(target_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _normalize(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

    def store(self, *, saga_id: str, step: str, kind: str, payload: Any) -> Dict[str, Any]:
        serialized = self._normalize(payload)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        prefix = digest[:2]
        target_dir = self._base / prefix
        target_dir.mkdir(parents=True, exist_ok=True)

        file_name = f"{digest}.json"
        file_path = target_dir / file_name
        if not file_path.exists():
            file_path.write_text(serialized, encoding="utf-8")

        size_bytes = len(serialized.encode("utf-8"))
        return {
            "kind": kind,
            "saga_id": saga_id,
            "step": step,
            "uri": f"artifact://{prefix}/{file_name}",
            "sha256": digest,
            "bytes": size_bytes,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
