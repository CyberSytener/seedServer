"""
Diagnostic Core utilities: portfolio analysis, competency modeling, and skill matrix updates.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.llm.validator import LLMResponseValidator
from app.models.api import PortfolioAnalysis
from app.core.llm.router import ProviderError, execute_llm_request


logger = logging.getLogger(__name__)


def analyze_portfolio(
    payload: Dict[str, Any],
    *,
    provider: str = "gemini",
    model: str = "gemini-2.0-flash-exp",
    max_tokens: int = 1200,
) -> Dict[str, Any]:
    """
    Analyze portfolio evidence (links/text/projects) via LLM and extract skills.

    Returns a dict with status and analysis payload.
    """
    portfolio_urls = payload.get("portfolio_urls") or payload.get("portfolioUrls") or []
    portfolio_text = payload.get("portfolio_text") or payload.get("portfolioText") or ""
    projects = payload.get("projects") or []
    skills_hint = payload.get("skills") or []

    if not portfolio_urls and not portfolio_text and not projects and not skills_hint:
        return {
            "status": "skipped",
            "reason": "no_portfolio_data",
            "analysis": {
                "skills": [],
                "summary": "No portfolio data provided.",
                "domains": [],
                "red_flags": [],
            },
        }

    system_prompt = (
        "You are a portfolio analyzer. Extract skills with evidence and confidence. "
        "Output STRICT JSON matching this schema: "
        "{\"skills\":[{\"skill\":string,\"evidence\":string,\"confidence\":number,\"source\":string}],"
        "\"summary\":string,\"domains\":[string],\"red_flags\":[string]}"
    )
    user_prompt = json.dumps(
        {
            "portfolio_urls": portfolio_urls,
            "portfolio_text": portfolio_text,
            "projects": projects,
            "skills_hint": skills_hint,
        },
        ensure_ascii=False,
    )

    try:
        response_text = execute_llm_request(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            provider=provider,
            model=model,
            max_tokens=max_tokens,
            timeout_sec=60,
        )
    except ProviderError as exc:
        logger.warning("Portfolio analysis failed: %s", exc)
        return {
            "status": "error",
            "error": str(exc),
            "analysis": {
                "skills": [],
                "summary": "Portfolio analysis failed.",
                "domains": [],
                "red_flags": [],
            },
        }

    validator = LLMResponseValidator(logger=logger)
    result = validator.validate_json_structure(response_text, PortfolioAnalysis)
    if not result.is_valid or not result.data:
        logger.warning("Portfolio analysis validation failed: %s", result.error)
        return {
            "status": "error",
            "error": result.error or "invalid_portfolio_analysis",
            "analysis": {
                "skills": [],
                "summary": "Portfolio analysis invalid.",
                "domains": [],
                "red_flags": [],
            },
        }

    return {
        "status": "ok",
        "analysis": result.data.model_dump(by_alias=True),
        "warnings": result.warnings,
    }


def build_competency_model(
    *,
    diagnostic_results: Optional[Dict[str, Any]] = None,
    portfolio_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine diagnostic results and portfolio evidence into a competency model."""
    skills_map: Dict[str, Dict[str, Any]] = {}

    if diagnostic_results:
        skill_scores = diagnostic_results.get("skill_scores") or {}
        for skill, score in skill_scores.items():
            skills_map[skill] = {
                "skill": skill,
                "score": float(score),
                "confidence": 0.7,
                "source": "diagnostic",
            }

    if portfolio_analysis:
        analysis = portfolio_analysis.get("analysis") or portfolio_analysis
        portfolio_skills = analysis.get("skills") or []
        for item in portfolio_skills:
            skill = item.get("skill")
            if not skill:
                continue
            confidence = float(item.get("confidence") or 0.5)
            score = max(10.0, min(100.0, 40.0 + (confidence * 60.0)))
            if skill in skills_map:
                existing = skills_map[skill]
                existing["score"] = max(existing["score"], score)
                existing["confidence"] = max(existing["confidence"], confidence)
                existing["source"] = "diagnostic+portfolio"
            else:
                skills_map[skill] = {
                    "skill": skill,
                    "score": score,
                    "confidence": confidence,
                    "source": "portfolio",
                }

    estimated_cefr = None
    if diagnostic_results:
        estimated_cefr = diagnostic_results.get("estimated_cefr")

    return {
        "estimated_cefr": estimated_cefr,
        "skills": list(skills_map.values()),
        "notes": "Generated by Diagnostic Core.",
    }


def get_skill_matrix(db: Any, user_id: str) -> Optional[Dict[str, Any]]:
    """Load current skill matrix JSON if present."""
    cursor = db._conn.execute(
        "SELECT matrix_json FROM skill_matrices WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    try:
        return json.loads(row[0])
    except Exception:
        return None


def upsert_skill_matrix(
    db: Any,
    *,
    user_id: str,
    matrix: Dict[str, Any],
    source: str = "diagnostic_core",
) -> Dict[str, Any]:
    """Persist skill matrix for a user (upsert)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    matrix_payload = json.dumps(matrix, ensure_ascii=False)

    db.execute(
        """
        INSERT INTO skill_matrices (user_id, matrix_json, version, updated_at, source)
        VALUES (?, ?, 1, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            matrix_json = excluded.matrix_json,
            version = skill_matrices.version + 1,
            updated_at = excluded.updated_at,
            source = excluded.source
        """,
        (user_id, matrix_payload, now_iso, source),
    )

    return {
        "user_id": user_id,
        "updated_at": now_iso,
        "source": source,
    }


def update_skill_matrix_from_diagnostic(
    db: Any,
    *,
    user_id: str,
    diagnostic_results: Dict[str, Any],
) -> Dict[str, Any]:
    """Update skill matrix after diagnostic session completion."""
    existing = get_skill_matrix(db, user_id) or {}
    portfolio_analysis = existing.get("portfolio_analysis")

    competency_model = build_competency_model(
        diagnostic_results=diagnostic_results,
        portfolio_analysis=portfolio_analysis,
    )

    matrix = {
        "status": "diagnostic_complete",
        "diagnostic_results": diagnostic_results,
        "portfolio_analysis": portfolio_analysis,
        "competency_model": competency_model,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    return upsert_skill_matrix(
        db,
        user_id=user_id,
        matrix=matrix,
        source="diagnostic_results",
    )

