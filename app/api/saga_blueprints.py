from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.auth import verify_user_context
from app.core.blocks import BlockRegistry, build_default_registry, get_registry_schema
from app.core.realtime.sagas.flows.dynamic_saga import DynamicSaga, ExecutionMode
from app.core.saga_blueprints import BlueprintStatus, RunRecord, blueprint_store, run_store
from app.core.safety import SafetyValidator
from app.infrastructure.db.pgvector_store import PgvectorStore
from app.infrastructure.db.postgres import AsyncPGDatabase
from app.services.blueprint_gallery import seed_blueprint_gallery
from app.services.dynamic_block_loader import BlockDraftResult, DynamicBlockLoader
from app.services.dynamic_publish_gate import evaluate_publish_gate, record_publish_decision
from app.services.inventory_provider import PostgresInventoryProvider
from app.services.job.cache import PostgresScanCache
from app.services.job.scanner import JobScanner
from app.services.job.scorer import GeminiEmbedder, JobScorer, ScoringConfig
from app.services.job.sources import ArbetsformedlingenSource, RemotiveJobSource
from app.services.saga_architect import SagaArchitect
from app.services.saga_reporter import SagaReporter
from app.services.summary_engine import SummaryEngine
from app.services.trace_analyzer import TraceAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/sagas", tags=["Saga Blueprints"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class SagaBaseModel(BaseModel):
    model_config = {"protected_namespaces": ()}


class SagaBlueprintStep(SagaBaseModel):
    id: Optional[str] = None
    block: Optional[str] = None
    block_type: Optional[str] = None
    params: Dict[str, Any] = Field(default_factory=dict)
    inputs: Dict[str, Any] = Field(default_factory=dict)


class SagaBlueprint(SagaBaseModel):
    name: str
    version: str = "v1"
    steps: List[SagaBlueprintStep]


class ExecuteSagaRequest(SagaBaseModel):
    payload: Dict[str, Any]
    mode: str = "LIVE"


class PerformanceMetrics(SagaBaseModel):
    duration_ms: int = 0
    cost_estimate: float = 0.0
    reliability_score: float = 1.0


class ExecuteSagaResponse(SagaBaseModel):
    blueprint: str
    run_id: Optional[str] = None
    status: str
    execution_mode: str = "LIVE"
    failed_step_id: Optional[str] = None
    failed_block: Optional[str] = None
    scan_id: Optional[str] = None
    scored_count: int = 0
    job_count: int = 0
    source_counts: Dict[str, int] = Field(default_factory=dict)
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
    performance: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    ai_summary: Optional[str] = None


class SandboxBlueprintResponse(SagaBaseModel):
    name: str
    status: str
    dry_run: Dict[str, Any]


class DraftSagaRequest(SagaBaseModel):
    prompt: str
    intent: Optional[str] = None
    owner_id: Optional[str] = None
    model_tier: Optional[str] = None
    publish_gate: Dict[str, Any] = Field(default_factory=dict)


class SafeDraftResponse(SagaBaseModel):
    ok: bool
    blueprint: Dict[str, Any]
    blueprint_id: Optional[str] = None
    status: str = "DRAFT"
    model: Optional[Dict[str, Any]] = None
    validation_errors: List[str] = Field(default_factory=list)
    safety: Dict[str, Any] = Field(default_factory=dict)
    dry_run: Optional[Dict[str, Any]] = None
    ai_summary: Optional[str] = None
    artifact_type: str = "blueprint"
    block: Optional[Dict[str, Any]] = None
    publish_gate: Optional[Dict[str, Any]] = None


class DeployBlueprintRequest(SagaBaseModel):
    blueprint: Dict[str, Any]
    owner_id: Optional[str] = None


class DeployBlueprintResponse(SagaBaseModel):
    blueprint_id: str
    status: str = "DRAFT"


class BlueprintInfoResponse(SagaBaseModel):
    name: str
    owner_id: str
    status: str
    created_at: str
    updated_at: str
    data: Dict[str, Any]


class RunSummaryResponse(SagaBaseModel):
    run_id: str
    blueprint_name: str
    owner_id: str
    status: str
    execution_mode: str
    created_at: str


class RunDetailResponse(SagaBaseModel):
    run_id: str
    blueprint_name: str
    owner_id: str
    status: str
    execution_mode: str
    request_payload: Dict[str, Any]
    result: Dict[str, Any]
    execution_trace: List[Dict[str, Any]]
    performance: Dict[str, Any]
    ai_summary: Optional[str] = None
    created_at: str
    updated_at: str


class ModuleStatResponse(SagaBaseModel):
    block: str
    run_count: int = 0
    step_count: int = 0
    avg_elapsed_sec: float = 0.0
    last_seen: Optional[str] = None


class SummaryRequest(SagaBaseModel):
    model_tier: Optional[str] = None
    include_fix: bool = True


class SummaryResponse(SagaBaseModel):
    model_name: str
    model_tier: Optional[str] = None
    summary: str
    fix_suggestion: Optional[str] = None


class TraceAnalysisRequest(SagaBaseModel):
    execution_trace: List[Dict[str, Any]]
    performance: Optional[Dict[str, Any]] = None
    blueprint: Optional[Dict[str, Any]] = None
    run_id: Optional[str] = None


class TraceAnalysisResponse(SagaBaseModel):
    model_name: str
    model_tier: Optional[str] = None
    summary: str


# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

class SimpleEngine:
    def __init__(self, db: Any, adapters: Dict[str, Any]):
        self.db = db
        self.adapters = adapters

    async def execute_step_plan(
        self,
        *,
        saga_id: str,
        saga_type: str,
        payload: Dict[str, Any],
        steps: List[Dict[str, Any]],
        step_plan: List[Any],
        correlation_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        result_payload: Dict[str, Any] = {}
        for step_def in step_plan:
            step_result = await step_def.execute()
            if step_result and step_result.result:
                result_payload.update(step_result.result)
        return {"status": "succeeded", "result": result_payload, "steps": steps}


def _get_db_dsn() -> Optional[str]:
    candidate = os.getenv("SEED_SAGA_DB_URL") or os.getenv("DATABASE_URL")
    if candidate and str(candidate).strip():
        return str(candidate).strip()
    return None


def _normalize_ctx_user_id(raw_user_id: Any) -> Optional[str]:
    normalized = str(raw_user_id or "").strip()
    if not normalized or normalized.lower() in {"unknown", "anonymous", "none"}:
        return None
    return normalized


def _with_effective_user_id(
    payload: Dict[str, Any],
    *,
    actor_user_id: Optional[str],
    execution_mode: ExecutionMode,
) -> Dict[str, Any]:
    normalized_payload = dict(payload or {})
    nested_request = normalized_payload.get("request")
    request_payload = dict(nested_request) if isinstance(nested_request, dict) else None

    explicit_user_id = (
        (request_payload or {}).get("user_id")
        or normalized_payload.get("user_id")
    )
    resolved_user_id = str(explicit_user_id or "").strip() or _normalize_ctx_user_id(actor_user_id)
    if not resolved_user_id:
        if execution_mode == ExecutionMode.LIVE:
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "missing_user_id",
                    "message": "LIVE execution requires user_id in payload or auth context.",
                },
            )
        resolved_user_id = "anonymous"

    normalized_payload.setdefault("user_id", resolved_user_id)
    if request_payload is not None:
        request_payload.setdefault("user_id", resolved_user_id)
        normalized_payload["request"] = request_payload
    return normalized_payload


def _get_saga_db_from_request(request: Optional[Request]) -> Optional[AsyncPGDatabase]:
    if not request:
        return None
    saga_db = getattr(request.app.state, "saga_db", None)
    if isinstance(saga_db, AsyncPGDatabase):
        return saga_db
    return None


def _get_inventory_provider(db: Optional[AsyncPGDatabase]) -> Optional[PostgresInventoryProvider]:
    if db is None:
        return None
    cache_ttl = int(os.getenv("SEED_INVENTORY_CACHE_TTL_SEC", "60"))
    return PostgresInventoryProvider(db, cache_ttl_sec=cache_ttl)


async def _fetch_stock_snapshot(db: Optional[AsyncPGDatabase]) -> List[Dict[str, Any]]:
    if db is None:
        return []
    try:
        rows = await db.fetch(
            """
            SELECT ingredient_name, quantity, unit, barcode
            FROM stock_levels
            ORDER BY ingredient_name
            """,
        )
        return [dict(row) for row in rows]
    except Exception:
        return []


def _validate_blueprint(blueprint: Dict[str, Any], registry: BlockRegistry) -> None:
    architect = SagaArchitect(registry)
    result = architect.validate_blueprint(blueprint)
    if not result.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_blueprint",
                "details": result.get("errors", []),
                "available": registry.list_blocks(),
            },
        )


def _resolve_admin_from_claims(claims: Dict[str, Any]) -> bool:
    if not claims:
        return False
    if claims.get("is_admin") is True or claims.get("admin") is True:
        return True
    role = claims.get("role")
    if isinstance(role, str) and role.lower() == "admin":
        return True
    roles = claims.get("roles")
    if isinstance(roles, list) and any(str(r).lower() == "admin" for r in roles):
        return True
    permissions = claims.get("permissions") or claims.get("scopes")
    if isinstance(permissions, list) and any(str(p).lower() == "admin" for p in permissions):
        return True
    if isinstance(permissions, str) and "admin" in permissions.lower().split():
        return True
    return False


def _get_auth_context(authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization:
        return {"user_id": "anonymous", "is_admin": False, "claims": {}}
    claims = verify_user_context(authorization)
    if not claims:
        raise HTTPException(status_code=401, detail="invalid_token")
    return {
        "user_id": claims.get("user_id", "unknown"),
        "is_admin": _resolve_admin_from_claims(claims),
        "claims": claims,
    }


def _require_admin(context: Dict[str, Any], action: str) -> None:
    if context.get("is_admin"):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "error": "admin_required",
            "action": action,
            "message": "Admin privileges required for this action.",
        },
    )


def _looks_like_block_request(prompt: str) -> bool:
    lowered = (prompt or "").lower()
    markers = [
        "create a block",
        "build a block",
        "new block",
        "block that",
        "saga block",
    ]
    return any(marker in lowered for marker in markers)


def _module_stats_from_runs(records: List[RunRecord]) -> List[ModuleStatResponse]:
    stats: Dict[str, Dict[str, Any]] = {}
    for record in records:
        seen_blocks: set[str] = set()
        for entry in record.execution_trace or []:
            block = str(entry.get("block") or "").strip()
            if not block:
                continue
            bucket = stats.setdefault(
                block,
                {
                    "run_count": 0,
                    "step_count": 0,
                    "elapsed_sum": 0.0,
                    "elapsed_count": 0,
                    "last_seen": None,
                },
            )
            bucket["step_count"] += 1
            elapsed = entry.get("elapsed_sec")
            if isinstance(elapsed, (int, float)):
                bucket["elapsed_sum"] += float(elapsed)
                bucket["elapsed_count"] += 1
            if block not in seen_blocks:
                bucket["run_count"] += 1
                seen_blocks.add(block)
            if record.created_at and (
                bucket["last_seen"] is None or record.created_at > bucket["last_seen"]
            ):
                bucket["last_seen"] = record.created_at

    results: List[ModuleStatResponse] = []
    for block, bucket in stats.items():
        avg = 0.0
        if bucket["elapsed_count"]:
            avg = bucket["elapsed_sum"] / float(bucket["elapsed_count"])
        last_seen = bucket["last_seen"]
        results.append(
            ModuleStatResponse(
                block=block,
                run_count=bucket["run_count"],
                step_count=bucket["step_count"],
                avg_elapsed_sec=round(avg, 4),
                last_seen=last_seen.isoformat() if last_seen else None,
            )
        )
    results.sort(key=lambda item: item.step_count, reverse=True)
    return results


async def _run_saga(
    stored: Dict[str, Any],
    payload: Dict[str, Any],
    registry: BlockRegistry,
    execution_mode: ExecutionMode = ExecutionMode.LIVE,
    db: Optional[AsyncPGDatabase] = None,
    actor_user_id: Optional[str] = None,
) -> Dict[str, Any]:
    safe_payload = _with_effective_user_id(
        payload,
        actor_user_id=actor_user_id,
        execution_mode=execution_mode,
    )

    resolved_db = db
    if resolved_db is None:
        dsn = _get_db_dsn()
        if dsn:
            try:
                resolved_db = await AsyncPGDatabase.get_shared(dsn)
            except Exception as exc:
                if execution_mode == ExecutionMode.LIVE:
                    raise HTTPException(
                        status_code=503,
                        detail={
                            "error": "postgres_unavailable",
                            "message": "Postgres connection failed for LIVE saga execution.",
                        },
                    ) from exc
                logger.warning("Saga dry-run without Postgres due to connection failure: %s", exc)
        elif execution_mode == ExecutionMode.LIVE:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "postgres_not_configured",
                    "message": "Postgres not configured. Set SEED_SAGA_DB_URL or DATABASE_URL.",
                },
            )

    is_live = execution_mode == ExecutionMode.LIVE

    if is_live:
        cache_ttl = int(os.getenv("SEED_JOB_SCAN_CACHE_TTL_SEC", "300"))
        scan_cache = PostgresScanCache(resolved_db, ttl_seconds=cache_ttl) if resolved_db is not None else None
        sources = [ArbetsformedlingenSource(), RemotiveJobSource()]
        scanner = JobScanner(sources, cache=scan_cache)
    else:
        class _NoopScanResult:
            jobs: List[Any] = []
            source_counts: Dict[str, int] = {}

        class _NoopScanner:
            async def scan_for_user(self, user_id: str, persona: Dict[str, Any]) -> _NoopScanResult:
                return _NoopScanResult()

        sources: List[Any] = []
        scanner = _NoopScanner()

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    embed_model = os.getenv("SEED_GEMINI_EMBED_MODEL", "text-embedding-004")
    embedder = None
    if gemini_key:
        try:
            embedder = GeminiEmbedder(api_key=gemini_key, model=embed_model)
        except Exception as exc:
            logger.warning("Gemini embedder disabled: %s", exc)
            embedder = None
    if is_live and resolved_db is not None:
        scorer = JobScorer(
            vector_store=PgvectorStore(resolved_db),
            db=resolved_db,
            config=ScoringConfig(embedding_model=embed_model),
            embedder=embedder,
        )
    else:
        class _NoopScorer:
            async def score_batch(self, **_: Any) -> List[Any]:
                return []

        scorer = _NoopScorer()

    provider = _get_inventory_provider(resolved_db) if is_live else None

    engine = SimpleEngine(
        db=resolved_db,
        adapters={
            "job_scanner": scanner,
            "job_scorer": scorer,
            "job_sources": sources,
            "inventory_provider": provider,
        },
    )

    saga = DynamicSaga(
        engine=engine,
        blueprint=stored.get("steps", []),
        registry=registry,
        execution_mode=execution_mode,
    )
    return await saga.run(
        saga_id=str(uuid.uuid4()),
        payload=safe_payload,
        steps=[],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/blueprints", response_model=SagaBlueprint)
async def save_blueprint(
    blueprint: SagaBlueprint,
    authorization: Optional[str] = Header(None),
) -> SagaBlueprint:
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "save_blueprint")
    await blueprint_store.save(
        blueprint.name,
        blueprint.model_dump(),
        owner_id=ctx.get("user_id", "system"),
        status=BlueprintStatus.ACTIVE,
    )
    return blueprint


@router.get("/blueprints/{blueprint_name}")
async def get_blueprint(blueprint_name: str) -> BlueprintInfoResponse:
    record = await blueprint_store.get_record(blueprint_name)
    if not record:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    return BlueprintInfoResponse(
        name=record.name,
        owner_id=record.owner_id,
        status=record.status.value,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
        data=record.data,
    )


@router.get("/blueprints")
async def list_blueprints(owner_id: Optional[str] = None) -> Dict[str, Any]:
    records = await blueprint_store.list_records(owner_id=owner_id)
    return {
        "blueprints": [
            {
                "name": r.name,
                "owner_id": r.owner_id,
                "status": r.status.value,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]
    }


@router.post("/execute/{blueprint_name}", response_model=ExecuteSagaResponse)
async def execute_blueprint(
    blueprint_name: str,
    request: ExecuteSagaRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
) -> ExecuteSagaResponse:
    stored = await blueprint_store.get(blueprint_name)
    if not stored:
        raise HTTPException(status_code=404, detail="blueprint_not_found")

    ctx = _get_auth_context(authorization)

    registry = build_default_registry()
    _validate_blueprint(stored, registry)

    requested = request.mode.upper()
    mode = ExecutionMode.DRY_RUN if requested == "DRY_RUN" else ExecutionMode.LIVE
    if not ctx.get("is_admin") and mode == ExecutionMode.LIVE:
        mode = ExecutionMode.DRY_RUN
    run_payload = _with_effective_user_id(
        request.payload,
        actor_user_id=ctx.get("user_id"),
        execution_mode=mode,
    )

    t0 = time.monotonic()
    result = await _run_saga(
        stored,
        run_payload,
        registry,
        execution_mode=mode,
        db=_get_saga_db_from_request(http_request),
        actor_user_id=ctx.get("user_id"),
    )
    duration_ms = int((time.monotonic() - t0) * 1000)

    result_payload = result.get("result", {}) if isinstance(result, dict) else {}
    jobs = result_payload.get("jobs") or []
    source_counts = result_payload.get("source_counts") or {}
    execution_trace = result.get("execution_trace", []) if isinstance(result, dict) else []
    execution_mode = result.get("execution_mode", "LIVE") if isinstance(result, dict) else "LIVE"
    failed_step_id = result.get("failed_step_id") if isinstance(result, dict) else None
    failed_block = result.get("failed_block") if isinstance(result, dict) else None

    # Performance metrics
    step_count = len(execution_trace)
    credit_cost = step_count * (0.5 if mode == ExecutionMode.DRY_RUN else 1.0)
    retries = sum(1 for e in execution_trace if e.get("retried"))
    reliability = 1.0 - (retries / max(step_count, 1))
    perf = PerformanceMetrics(
        duration_ms=duration_ms,
        cost_estimate=round(credit_cost, 2),
        reliability_score=round(reliability, 4),
    )

    # AI summary
    ai_summary: Optional[str] = None
    try:
        reporter = SagaReporter()
        ai_summary = await reporter.generate_summary(result)
    except Exception as exc:
        logger.warning("AI summary failed: %s", exc)

    run_id = str(uuid.uuid4())
    try:
        await run_store.save(
            RunRecord(
                run_id=run_id,
                blueprint_name=blueprint_name,
                owner_id=ctx.get("user_id", "system"),
                status=result.get("status", "unknown") if isinstance(result, dict) else "unknown",
                execution_mode=execution_mode,
                request_payload=run_payload,
                result=result_payload if isinstance(result_payload, dict) else {},
                execution_trace=execution_trace if isinstance(execution_trace, list) else [],
                performance=perf.model_dump(),
                ai_summary=ai_summary,
            )
        )
    except Exception as exc:
        logger.warning("Run persistence failed: %s", exc)
        run_id = None

    return ExecuteSagaResponse(
        blueprint=blueprint_name,
        run_id=run_id,
        status=result.get("status", "unknown") if isinstance(result, dict) else "unknown",
        execution_mode=execution_mode,
        failed_step_id=failed_step_id,
        failed_block=failed_block,
        scan_id=result_payload.get("scan_id"),
        scored_count=int(result_payload.get("scored_count") or 0),
        job_count=len(jobs) if isinstance(jobs, list) else 0,
        source_counts=source_counts if isinstance(source_counts, dict) else {},
        execution_trace=execution_trace,
        performance=perf,
        ai_summary=ai_summary,
    )


@router.get("/runs")
async def list_runs(
    blueprint_name: Optional[str] = None,
    owner_id: Optional[str] = None,
    limit: int = 200,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    ctx = _get_auth_context(authorization)
    effective_owner = owner_id
    if not ctx.get("is_admin"):
        effective_owner = ctx.get("user_id")
    records = await run_store.list_runs(
        blueprint_name=blueprint_name,
        owner_id=effective_owner,
        limit=limit,
    )
    return {
        "runs": [
            RunSummaryResponse(
                run_id=r.run_id,
                blueprint_name=r.blueprint_name,
                owner_id=r.owner_id,
                status=r.status,
                execution_mode=r.execution_mode,
                created_at=r.created_at.isoformat(),
            ).model_dump()
            for r in records
        ]
    }


@router.get("/runs/module-stats")
async def get_module_stats(
    blueprint_name: Optional[str] = None,
    owner_id: Optional[str] = None,
    limit: int = 200,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    ctx = _get_auth_context(authorization)
    effective_owner = owner_id
    if not ctx.get("is_admin"):
        effective_owner = ctx.get("user_id")
    records = await run_store.list_runs(
        blueprint_name=blueprint_name,
        owner_id=effective_owner,
        limit=limit,
    )
    return {
        "total_runs": len(records),
        "modules": [m.model_dump() for m in _module_stats_from_runs(records)],
    }


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    authorization: Optional[str] = Header(None),
) -> RunDetailResponse:
    ctx = _get_auth_context(authorization)
    record = await run_store.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run_not_found")
    if not ctx.get("is_admin") and record.owner_id not in ("system", ctx.get("user_id")):
        raise HTTPException(status_code=404, detail="run_not_found")
    return RunDetailResponse(
        run_id=record.run_id,
        blueprint_name=record.blueprint_name,
        owner_id=record.owner_id,
        status=record.status,
        execution_mode=record.execution_mode,
        request_payload=record.request_payload,
        result=record.result,
        execution_trace=record.execution_trace,
        performance=record.performance,
        ai_summary=record.ai_summary,
        created_at=record.created_at.isoformat(),
        updated_at=record.updated_at.isoformat(),
    )


@router.post("/runs/{run_id}/summary", response_model=SummaryResponse)
async def summarize_run(
    run_id: str,
    request: SummaryRequest,
    authorization: Optional[str] = Header(None),
) -> SummaryResponse:
    ctx = _get_auth_context(authorization)
    record = await run_store.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail="run_not_found")
    if not ctx.get("is_admin") and record.owner_id not in ("system", ctx.get("user_id")):
        raise HTTPException(status_code=404, detail="run_not_found")

    failed_entry = None
    for entry in record.execution_trace or []:
        if entry.get("status") == "failed":
            failed_entry = entry
            break

    execution_result = {
        "status": record.status,
        "execution_mode": record.execution_mode,
        "execution_trace": record.execution_trace,
        "result": record.result,
        "failed_step_id": failed_entry.get("step") if failed_entry else None,
        "failed_block": failed_entry.get("block") if failed_entry else None,
        "error": failed_entry.get("error") if failed_entry else None,
    }

    engine = SummaryEngine(gemini_api_key=os.getenv("GEMINI_API_KEY"))
    summary = await engine.summarize(
        execution_result=execution_result,
        model_tier=request.model_tier,
        include_fix=request.include_fix,
    )
    return SummaryResponse(
        model_name=summary["model_name"],
        model_tier=summary.get("model_tier"),
        summary=summary["summary"],
        fix_suggestion=summary.get("fix_suggestion"),
    )


@router.post("/analyze-trace", response_model=TraceAnalysisResponse)
async def analyze_trace(
    request: TraceAnalysisRequest,
    authorization: Optional[str] = Header(None),
) -> TraceAnalysisResponse:
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "analyze_trace")

    analyzer = TraceAnalyzer(gemini_api_key=os.getenv("GEMINI_API_KEY"))
    result = await analyzer.analyze(
        execution_trace=request.execution_trace,
        performance=request.performance,
        blueprint=request.blueprint,
        run_id=request.run_id,
        model_tier="powerful",
    )
    return TraceAnalysisResponse(
        model_name=result["model_name"],
        model_tier=result.get("model_tier"),
        summary=result["summary"],
    )


@router.get("/registry/schema")
async def get_registry_schema_endpoint() -> Dict[str, Any]:
    return get_registry_schema()


@router.get("/registry/prompt-context", response_class=PlainTextResponse)
async def get_registry_prompt_context(request: Request) -> str:
    registry = build_default_registry()
    db = _get_saga_db_from_request(request)
    provider = _get_inventory_provider(db)
    stock_snapshot = await provider.list_stock_snapshot() if provider else []
    architect = SagaArchitect(registry, inventory_provider=provider, stock_snapshot=stock_snapshot)
    return architect.generate_prompt_context(stock_snapshot)


@router.post("/blueprints/gallery/seed")
async def seed_blueprint_gallery_endpoint(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    import hmac as _hmac
    from app.settings import get_settings as _get_settings
    _s = _get_settings()
    _admin_key_header = request.headers.get("X-Admin-Key", "")
    _expected = str(_s.admin_key or "")
    if _expected and _admin_key_header and _hmac.compare_digest(_admin_key_header, _expected):
        names = await seed_blueprint_gallery()
        return {"seeded": names}
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "seed_blueprint_gallery")
    names = await seed_blueprint_gallery()
    return {"seeded": names}


@router.post("/architect/draft", response_model=SafeDraftResponse)
async def draft_blueprint_from_prompt(
    request: DraftSagaRequest,
    http_request: Request,
    authorization: Optional[str] = Header(None),
) -> SafeDraftResponse:
    """The 'Safe Draft' endpoint: generate -> validate -> safety check -> dry-run -> summarize."""
    ctx = _get_auth_context(authorization)
    owner_id = request.owner_id or ctx.get("user_id") or "anonymous"
    registry = build_default_registry()
    db = _get_saga_db_from_request(http_request)
    provider = _get_inventory_provider(db)
    stock_snapshot = await provider.list_stock_snapshot() if provider else []
    architect = SagaArchitect(registry, inventory_provider=provider, stock_snapshot=stock_snapshot)

    intent = (request.intent or "").lower().strip()
    if intent == "block" or (intent == "" and _looks_like_block_request(request.prompt)):
        block_result = BlockDraftResult(ok=False)
        meta: Optional[Dict[str, Any]] = None
        capability_scan: Optional[Dict[str, Any]] = None
        simulation_result: Optional[Dict[str, Any]] = None
        publish_gate_report: Optional[Dict[str, Any]] = None
        audit_log_path: Optional[str] = None
        gate_config = request.publish_gate if isinstance(request.publish_gate, dict) else {}
        run_simulation_requested = bool(gate_config.get("run_simulation"))
        approval_token = str(gate_config.get("approval_token") or "").strip() or None
        provided_simulation_ref = str(gate_config.get("simulation_artifact_ref") or "").strip() or None
        try:
            code, meta = await architect.draft_block_code(request.prompt, model_tier=request.model_tier)
            loader = DynamicBlockLoader(registry)
            errors = loader.validate_code(code)
            capability_scan = loader.scan_capabilities(code)
            for violation in capability_scan.get("violations") or []:
                if violation not in errors:
                    errors.append(str(violation))
            if errors:
                block_result.validation_errors = errors
            else:
                draft_cls = loader.load_block(code)
                block_name = getattr(draft_cls, "NAME", None) or draft_cls.__name__
                block_result.block_name = block_name
                block_result.code = code
                saved_path = loader.save_block(block_name, code)
                block_cls = loader.load_block_from_path(saved_path)
                dry_run = await loader.dry_run(block_cls)
                block_result.dry_run = dry_run
                if run_simulation_requested:
                    from app.sim.harness import run_simulation

                    sim_output_dir = Path(
                        os.getenv(
                            "SEED_DYNAMIC_BLOCK_SIM_OUTPUT_DIR",
                            ".seed_artifacts/dynamic_publish/simulation",
                        )
                    )
                    sim_output_dir.mkdir(parents=True, exist_ok=True)
                    sim_report = run_simulation(output_dir=sim_output_dir, include_modes=False)
                    sim_report_path = sim_output_dir / f"{sim_report.run_id}.json"
                    sim_report_path.write_text(
                        json.dumps(sim_report.to_dict(), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    simulation_result = {
                        "status": "passed" if sim_report.passed else "failed",
                        "passed": bool(sim_report.passed),
                        "run_id": sim_report.run_id,
                        "scenario_count": int(sim_report.scenario_count),
                        "failed_count": int(sim_report.failed_count),
                        "artifact_ref": str(sim_report_path),
                        "source": "run_simulation",
                    }
                elif provided_simulation_ref:
                    simulation_result = {
                        "status": "passed",
                        "passed": True,
                        "artifact_ref": provided_simulation_ref,
                        "source": "provided",
                    }

                publish_gate_report = evaluate_publish_gate(
                    dry_run_result=block_result.dry_run,
                    capability_scan=capability_scan,
                    simulation_result=simulation_result,
                    approval_token=approval_token,
                )
                if publish_gate_report.get("can_register"):
                    loader.register(block_name, block_cls)
                    block_result.status = "ACTIVE"
                else:
                    block_result.status = "SANDBOXED"
                    block_result.warnings.append(
                        f"publish_gate_blocked:{publish_gate_report.get('reason')}"
                    )
                block_result.ok = True
        except Exception as exc:
            block_result.validation_errors.append(str(exc))
            block_result.status = "DRAFT"

        if publish_gate_report is None:
            publish_gate_report = evaluate_publish_gate(
                dry_run_result=block_result.dry_run,
                capability_scan=capability_scan,
                simulation_result=simulation_result,
                approval_token=approval_token,
            )

        try:
            audit_log_path = record_publish_decision(
                block_name=block_result.block_name or "unknown_dynamic_block",
                actor_id=str(owner_id),
                gate_report=publish_gate_report,
                extra={
                    "artifact_type": "block",
                    "model": meta or {},
                    "validation_errors": list(block_result.validation_errors),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist dynamic block publish audit: %s", exc)

        return SafeDraftResponse(
            ok=block_result.ok,
            blueprint={},
            blueprint_id=None,
            status=block_result.status,
            model=meta,
            validation_errors=block_result.validation_errors,
            safety={
                "passed": block_result.ok,
                "reason": "block_draft",
            },
            dry_run=block_result.dry_run,
            ai_summary=None,
            artifact_type="block",
            publish_gate=publish_gate_report,
            block={
                "block_name": block_result.block_name,
                "code": block_result.code,
                "validation_errors": block_result.validation_errors,
                "warnings": block_result.warnings,
                "dry_run": block_result.dry_run,
                "capability_scan": capability_scan,
                "simulation": simulation_result,
                "publish_gate": publish_gate_report,
                "audit_log": audit_log_path,
                "status": block_result.status,
                "ok": block_result.ok,
            },
        )

    # 1. Generate blueprint via LLM (with model tier)
    blueprint, gen_meta = await architect.draft_blueprint(
        request.prompt,
        model_tier=request.model_tier,
        stock_snapshot=stock_snapshot,
    )

    # 2. Structural validation
    validation = architect.validate_blueprint(blueprint)
    if not validation.get("ok"):
        return SafeDraftResponse(
            ok=False,
            blueprint=blueprint,            model=gen_meta,            validation_errors=list(validation.get("errors", [])),
            safety={"passed": False, "reason": "Skipped — blueprint structurally invalid."},
        )

    # 3. Safety check (static + AI audit)
    validator = SafetyValidator()
    verdict = await validator.validate(blueprint)
    if not verdict.passed:
        return SafeDraftResponse(
            ok=False,
            blueprint=blueprint,
            model=gen_meta,
            safety=verdict.to_dict(),
        )

    # 4. Save as DRAFT
    blueprint_id = str(uuid.uuid4())
    blueprint_copy = dict(blueprint)
    blueprint_copy.setdefault("name", blueprint_id)
    await blueprint_store.save(
        blueprint_id, blueprint_copy, owner_id=owner_id, status=BlueprintStatus.DRAFT,
    )

    # 5. Dry-run in sandbox
    dry_run_result: Optional[Dict[str, Any]] = None
    ai_summary: Optional[str] = None
    try:
        raw = await _run_saga(
            blueprint_copy,
            {"user_id": "00000000-0000-0000-0000-000000000000"},
            registry,
            ExecutionMode.DRY_RUN,
            db=_get_saga_db_from_request(http_request),
        )
        result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
        jobs = result_payload.get("jobs") or []
        dry_run_result = {
            "status": raw.get("status", "unknown") if isinstance(raw, dict) else "unknown",
            "execution_mode": raw.get("execution_mode", "DRY_RUN"),
            "failed_step_id": raw.get("failed_step_id") if isinstance(raw, dict) else None,
            "failed_block": raw.get("failed_block") if isinstance(raw, dict) else None,
            "job_count": len(jobs) if isinstance(jobs, list) else 0,
            "scored_count": int(result_payload.get("scored_count") or 0),
            "execution_trace": raw.get("execution_trace", []) if isinstance(raw, dict) else [],
        }

        # 6. AI summary of dry-run
        try:
            reporter = SagaReporter()
            ai_summary = await reporter.generate_summary(raw)
        except Exception as exc:
            logger.warning("AI summary in draft failed: %s", exc)

        # Mark as SANDBOXED (dry-run passed)
        await blueprint_store.update_status(blueprint_id, BlueprintStatus.SANDBOXED)
    except Exception as exc:
        logger.warning("Dry-run failed: %s", exc)
        dry_run_result = {"status": "failed", "error": str(exc)}

    record = await blueprint_store.get_record(blueprint_id)
    return SafeDraftResponse(
        ok=True,
        blueprint=blueprint_copy,
        blueprint_id=blueprint_id,
        status=record.status.value if record else "DRAFT",
        model=gen_meta,
        safety=verdict.to_dict(),
        dry_run=dry_run_result,
        ai_summary=ai_summary,
    )


@router.post("/blueprints/deploy", response_model=DeployBlueprintResponse)
async def deploy_blueprint(
    request: DeployBlueprintRequest,
    authorization: Optional[str] = Header(None),
) -> DeployBlueprintResponse:
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "deploy_blueprint")
    owner_id = request.owner_id or ctx.get("user_id") or "anonymous"
    architect = SagaArchitect(build_default_registry())
    validation = architect.validate_blueprint(request.blueprint)
    if not validation.get("ok"):
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid_blueprint", "details": validation.get("errors", [])},
        )

    blueprint_id = str(uuid.uuid4())
    blueprint = dict(request.blueprint)
    blueprint.setdefault("name", blueprint_id)
    record = await blueprint_store.save(blueprint_id, blueprint, owner_id=owner_id, status=BlueprintStatus.DRAFT)
    return DeployBlueprintResponse(blueprint_id=blueprint_id, status=record.status.value)


@router.post("/blueprints/{blueprint_name}/sandbox", response_model=SandboxBlueprintResponse)
async def sandbox_blueprint(
    blueprint_name: str,
    http_request: Request,
    authorization: Optional[str] = Header(None),
) -> SandboxBlueprintResponse:
    """Dry-run an existing draft and mark as SANDBOXED on success."""
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "sandbox_blueprint")

    record = await blueprint_store.get_record(blueprint_name)
    if not record:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    if record.status not in (BlueprintStatus.DRAFT, BlueprintStatus.SANDBOXED):
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "current_status": record.status.value,
                "message": "Only DRAFT or SANDBOXED blueprints can be sandboxed.",
            },
        )

    registry = build_default_registry()
    _validate_blueprint(record.data, registry)

    dry_run_result: Dict[str, Any] = {}
    try:
        raw = await _run_saga(
            record.data,
            {"user_id": "00000000-0000-0000-0000-000000000000"},
            registry,
            ExecutionMode.DRY_RUN,
            db=_get_saga_db_from_request(http_request),
        )
        result_payload = raw.get("result", {}) if isinstance(raw, dict) else {}
        jobs = result_payload.get("jobs") or []
        dry_run_result = {
            "status": raw.get("status", "unknown") if isinstance(raw, dict) else "unknown",
            "execution_mode": raw.get("execution_mode", "DRY_RUN"),
            "failed_step_id": raw.get("failed_step_id") if isinstance(raw, dict) else None,
            "failed_block": raw.get("failed_block") if isinstance(raw, dict) else None,
            "job_count": len(jobs) if isinstance(jobs, list) else 0,
            "scored_count": int(result_payload.get("scored_count") or 0),
            "execution_trace": raw.get("execution_trace", []) if isinstance(raw, dict) else [],
        }

        if dry_run_result.get("status") == "succeeded":
            record = await blueprint_store.update_status(blueprint_name, BlueprintStatus.SANDBOXED)
    except Exception as exc:
        dry_run_result = {"status": "failed", "error": str(exc)}

    return SandboxBlueprintResponse(
        name=record.name,
        status=record.status.value,
        dry_run=dry_run_result,
    )


@router.post("/blueprints/{blueprint_name}/approve")
async def approve_blueprint(
    blueprint_name: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    """Human-in-the-loop approval: SANDBOXED -> ACTIVE."""
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "approve_blueprint")
    record = await blueprint_store.get_record(blueprint_name)
    if not record:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    if record.status != BlueprintStatus.SANDBOXED:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "invalid_transition",
                "current_status": record.status.value,
                "message": f"Only SANDBOXED blueprints can be approved. Current status: {record.status.value}",
            },
        )
    record = await blueprint_store.update_status(blueprint_name, BlueprintStatus.ACTIVE)
    return {"name": record.name, "status": record.status.value, "message": "Blueprint is now ACTIVE and ready for live execution."}


@router.post("/blueprints/{blueprint_name}/activate")
async def activate_blueprint(
    blueprint_name: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "activate_blueprint")
    record = await blueprint_store.update_status(blueprint_name, BlueprintStatus.ACTIVE)
    if not record:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    return {"name": record.name, "status": record.status.value}


@router.post("/blueprints/{blueprint_name}/archive")
async def archive_blueprint(
    blueprint_name: str,
    authorization: Optional[str] = Header(None),
) -> Dict[str, Any]:
    ctx = _get_auth_context(authorization)
    _require_admin(ctx, "archive_blueprint")
    record = await blueprint_store.update_status(blueprint_name, BlueprintStatus.ARCHIVED)
    if not record:
        raise HTTPException(status_code=404, detail="blueprint_not_found")
    return {"name": record.name, "status": record.status.value}
