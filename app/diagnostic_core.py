"""Compatibility bridge for diagnostic core helpers."""

from __future__ import annotations

from app.services.diagnostic.core import (
    analyze_portfolio,
    build_competency_model,
    get_skill_matrix,
    update_skill_matrix_from_diagnostic,
    upsert_skill_matrix,
)


__all__ = [
    "analyze_portfolio",
    "build_competency_model",
    "get_skill_matrix",
    "upsert_skill_matrix",
    "update_skill_matrix_from_diagnostic",
]
