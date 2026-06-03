"""Career learning: editable analysis, tracks, and background lessons."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.infrastructure.db.sqlite import DB
from app.models.api import (
    CareerAnalysisPatchRequest,
    CareerAnalysisResponse,
    CareerLearningTrack,
    CareerModule,
    CareerLesson,
    CareerLessonCreateRequest,
    CareerUpskillingRequest,
    MarketGapData,
    UserBaseData,
    PlacementResults,
)
from app.services.career.upskilling import build_upskilling_plan


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _build_analysis_payload(req: CareerUpskillingRequest) -> dict:
    return {
        "user_base_data": req.user_base_data.model_dump(),
        "market_gap_data": req.market_gap_data.model_dump(),
        "placement_results": req.placement_results.model_dump() if req.placement_results else None,
        "target_role": req.target_role,
        "duration_weeks": req.duration_weeks,
        "success_threshold": req.success_threshold,
    }


def _analysis_from_row(row) -> CareerAnalysisResponse:
    payload = json.loads(row["analysis_json"])
    return CareerAnalysisResponse(
        analysis_id=row["id"],
        user_base_data=UserBaseData(**payload["user_base_data"]),
        market_gap_data=MarketGapData(**payload["market_gap_data"]),
        placement_results=PlacementResults(**payload["placement_results"]) if payload.get("placement_results") else None,
        target_role=payload.get("target_role"),
        duration_weeks=int(payload.get("duration_weeks", 8)),
        success_threshold=int(payload.get("success_threshold", 85)),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_analysis(db: DB, user_id: str, req: CareerUpskillingRequest) -> CareerAnalysisResponse:
    analysis_id = _new_id("analysis")
    payload = _build_analysis_payload(req)
    now = _now_iso()

    db.execute(
        """
        INSERT INTO career_analyses (id, user_id, analysis_json, status, created_at, updated_at)
        VALUES (?, ?, ?, 'active', ?, ?)
        """,
        (analysis_id, user_id, json.dumps(payload), now, now)
    )

    row = db.fetchone("SELECT * FROM career_analyses WHERE id = ?", (analysis_id,))
    return _analysis_from_row(row)


def get_analysis(db: DB, user_id: str, analysis_id: str) -> Optional[CareerAnalysisResponse]:
    row = db.fetchone(
        "SELECT * FROM career_analyses WHERE id = ? AND user_id = ?",
        (analysis_id, user_id)
    )
    if not row:
        return None
    return _analysis_from_row(row)


def patch_analysis(
    db: DB,
    user_id: str,
    analysis_id: str,
    patch: CareerAnalysisPatchRequest
) -> Optional[CareerAnalysisResponse]:
    row = db.fetchone(
        "SELECT * FROM career_analyses WHERE id = ? AND user_id = ?",
        (analysis_id, user_id)
    )
    if not row:
        return None

    payload = json.loads(row["analysis_json"])

    if patch.user_base_data is not None:
        payload["user_base_data"] = patch.user_base_data.model_dump()
    if patch.market_gap_data is not None:
        payload["market_gap_data"] = patch.market_gap_data.model_dump()
    if patch.placement_results is not None:
        payload["placement_results"] = patch.placement_results.model_dump()
    if patch.target_role is not None:
        payload["target_role"] = patch.target_role
    if patch.duration_weeks is not None:
        payload["duration_weeks"] = patch.duration_weeks
    if patch.success_threshold is not None:
        payload["success_threshold"] = patch.success_threshold

    now = _now_iso()
    db.execute(
        "UPDATE career_analyses SET analysis_json = ?, updated_at = ? WHERE id = ?",
        (json.dumps(payload), now, analysis_id)
    )

    updated = db.fetchone("SELECT * FROM career_analyses WHERE id = ?", (analysis_id,))
    return _analysis_from_row(updated)


def _build_track_payload(analysis: CareerAnalysisResponse) -> dict:
    target_role = analysis.target_role or (
        analysis.user_base_data.target_roles[0] if analysis.user_base_data.target_roles else None
    )
    plan = build_upskilling_plan(
        missing_skills=analysis.market_gap_data.missing_skills,
        target_role=target_role,
        duration_weeks=analysis.duration_weeks,
    )

    modules = []
    for module in plan.modules:
        modules.append(
            {
                "module_id": _new_id("mod"),
                "title": module.title,
                "objectives": module.objectives,
                "recommended_activities": module.recommended_activities,
                "status": "planned",
            }
        )

    return {
        "analysis_id": analysis.analysis_id,
        "target_role": target_role,
        "modules": modules,
    }


def _track_from_row(row) -> CareerLearningTrack:
    payload = json.loads(row["track_json"])
    modules = [CareerModule(**m) for m in payload.get("modules", [])]
    return CareerLearningTrack(
        track_id=row["id"],
        analysis_id=payload["analysis_id"],
        target_role=payload.get("target_role"),
        modules=modules,
        progress_percent=float(row["progress_percent"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_track(db: DB, user_id: str, analysis: CareerAnalysisResponse) -> CareerLearningTrack:
    track_id = _new_id("track")
    payload = _build_track_payload(analysis)
    now = _now_iso()

    db.execute(
        """
        INSERT INTO career_tracks (id, user_id, analysis_id, track_json, progress_percent, created_at, updated_at)
        VALUES (?, ?, ?, ?, 0.0, ?, ?)
        """,
        (track_id, user_id, analysis.analysis_id, json.dumps(payload), now, now)
    )

    row = db.fetchone("SELECT * FROM career_tracks WHERE id = ?", (track_id,))
    return _track_from_row(row)


def list_tracks(db: DB, user_id: str) -> list[CareerLearningTrack]:
    rows = db.fetchall(
        "SELECT * FROM career_tracks WHERE user_id = ? ORDER BY updated_at DESC",
        (user_id,)
    )
    return [_track_from_row(r) for r in rows]


def get_track(db: DB, user_id: str, track_id: str) -> Optional[CareerLearningTrack]:
    row = db.fetchone(
        "SELECT * FROM career_tracks WHERE id = ? AND user_id = ?",
        (track_id, user_id)
    )
    if not row:
        return None
    return _track_from_row(row)


def set_module_status(
    db: DB,
    user_id: str,
    track_id: str,
    module_id: str,
    status: str
) -> Optional[CareerLearningTrack]:
    row = db.fetchone(
        "SELECT * FROM career_tracks WHERE id = ? AND user_id = ?",
        (track_id, user_id)
    )
    if not row:
        return None

    payload = json.loads(row["track_json"])
    updated = False
    for module in payload.get("modules", []):
        if module.get("module_id") == module_id:
            module["status"] = status
            updated = True
            break

    if not updated:
        return None

    total = len(payload.get("modules", []))
    completed = len([m for m in payload.get("modules", []) if m.get("status") == "completed"])
    progress_percent = (completed / total) * 100 if total > 0 else 0.0

    now = _now_iso()
    db.execute(
        "UPDATE career_tracks SET track_json = ?, progress_percent = ?, updated_at = ? WHERE id = ?",
        (json.dumps(payload), progress_percent, now, track_id)
    )

    updated_row = db.fetchone("SELECT * FROM career_tracks WHERE id = ?", (track_id,))
    return _track_from_row(updated_row)


def create_lesson(
    db: DB,
    user_id: str,
    track_id: str,
    req: CareerLessonCreateRequest
) -> CareerLesson:
    lesson_id = _new_id("lesson")
    now = _now_iso()

    payload = {
        "title": req.title,
        "content": req.content,
    }

    db.execute(
        """
        INSERT INTO career_lessons (id, user_id, track_id, module_id, lesson_json, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'ready', ?, ?)
        """,
        (lesson_id, user_id, track_id, req.module_id, json.dumps(payload), now, now)
    )

    return CareerLesson(
        lesson_id=lesson_id,
        track_id=track_id,
        module_id=req.module_id,
        title=req.title,
        content=req.content,
        status="ready",
        created_at=now,
        updated_at=now,
    )


def list_lessons(db: DB, user_id: str, status: Optional[str] = None) -> list[CareerLesson]:
    if status:
        rows = db.fetchall(
            "SELECT * FROM career_lessons WHERE user_id = ? AND status = ? ORDER BY updated_at DESC",
            (user_id, status)
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM career_lessons WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,)
        )

    lessons: list[CareerLesson] = []
    for row in rows:
        payload = json.loads(row["lesson_json"])
        lessons.append(
            CareerLesson(
                lesson_id=row["id"],
                track_id=row["track_id"],
                module_id=row["module_id"],
                title=payload.get("title", "Untitled Lesson"),
                content=payload.get("content", {}),
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
        )

    return lessons


def update_lesson_status(
    db: DB,
    user_id: str,
    lesson_id: str,
    status: str
) -> Optional[CareerLesson]:
    row = db.fetchone(
        "SELECT * FROM career_lessons WHERE id = ? AND user_id = ?",
        (lesson_id, user_id)
    )
    if not row:
        return None

    payload = json.loads(row["lesson_json"])
    now = _now_iso()
    db.execute(
        "UPDATE career_lessons SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, lesson_id)
    )

    return CareerLesson(
        lesson_id=lesson_id,
        track_id=row["track_id"],
        module_id=row["module_id"],
        title=payload.get("title", "Untitled Lesson"),
        content=payload.get("content", {}),
        status=status,
        created_at=row["created_at"],
        updated_at=now,
    )




