from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone

import redis.asyncio as redis

from app.infrastructure.db.sqlite import DB
from .queue import RedisQueueHub
from .redisutil import RedisPool
from app.core.interfaces.action_executor import ActionExecutor
from app.infrastructure.llm.action_executor import InfrastructureActionExecutor
from .sse import RedisEventBroker


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if not val:
        return None
    try:
        if "T" in val:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        return datetime.strptime(val, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


async def process_job(
    *,
    db: DB,
    broker: RedisEventBroker,
    job_id: str,
    executor: ActionExecutor,
    worker_name: str = "worker",
) -> None:
    row = db.fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
    if row is None:
        return
    if row["status"] != "queued":
        return
    
    # Check if this is a path job
    action = row["action"]
    if action == "path_node_generate":
        from app.services.path.worker import process_path_node_generation
        await process_path_node_generation(db=db, broker=broker, job_id=job_id)
        return

    not_before = _parse_dt(row["not_before"])
    if not_before is not None and not_before > datetime.now(timezone.utc):
        # too early; worker shouldn't process this job. leave queued.
        return

    user_id = row["user_id"]
    claim_started_at = _now_iso()

    try:
        db.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
            (claim_started_at, job_id),
        )

        claimed = db.fetchone("SELECT status, started_at FROM jobs WHERE id = ?", (job_id,))
        if not claimed:
            return
        if claimed["status"] != "running" or str(claimed["started_at"] or "") != claim_started_at:
            return

        db.execute(
            "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
            (
                job_id,
                "running",
                json.dumps({"worker": worker_name, "claim_started_at": claim_started_at}),
            ),
        )

        opts = {}
        try:
            opts = json.loads(row["options_json"] or "{}")
        except Exception:
            opts = {}
        correlation_id = str(opts.get("correlation_id") or opts.get("correlationId") or "").strip() or None

        # Extract persona_id from options or use stored persona_id_used
        persona_id = opts.get("persona_id") or opts.get("personaId")
        if not persona_id and "persona_id_used" in row.keys():
            persona_id = row["persona_id_used"]

        res = await executor.execute_action(
            row["action"],
            row["input_text"] or "",
            opts,
            row["mode"],
            persona_id,
        )

        db.execute(
            """
            UPDATE jobs
            SET status='done',
                provider=?, model=?, persona_id_used=?,
                tokens_in_actual=?, tokens_out_actual=?, cost_usd_actual=?,
                result_text=?, finished_at=?
            WHERE id=?
            """,
            (
                res.provider,
                res.model,
                res.persona_id_used,
                res.tokens_in,
                res.tokens_out,
                float(res.cost_usd),
                res.text,
                _now_iso(),
                job_id,
            ),
        )
        db.execute(
            "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
            (job_id, "done", json.dumps({"correlation_id": correlation_id})),
        )
        await broker.publish(user_id, "job_done", {"job_id": job_id, "correlation_id": correlation_id})

    except Exception as e:
        msg = str(e)
        db.execute(
            "UPDATE jobs SET status='failed', error_code=?, error_message=?, finished_at=? WHERE id=?",
            ("error", msg[:2000], _now_iso(), job_id),
        )
        db.execute(
            "INSERT INTO job_events(job_id,event,data_json) VALUES(?,?,?)",
            (job_id, "failed", json.dumps({"correlation_id": correlation_id})),
        )
        await broker.publish(user_id, "job_failed", {"job_id": job_id, "correlation_id": correlation_id})


async def worker_loop(
    *,
    name: str,
    queue_name: str,
    db: DB,
    queuehub: RedisQueueHub,
    broker: RedisEventBroker,
    executor: ActionExecutor,
) -> None:
    while True:
        item = await queuehub.dequeue(queue_name, timeout_sec=10)
        if not item:
            continue
        await process_job(
            db=db,
            broker=broker,
            job_id=item.job_id,
            executor=executor,
            worker_name=name,
        )


async def main() -> None:
    db_path = os.getenv("SEED_DB_PATH", "./seed.db")
    redis_url = os.getenv("SEED_REDIS_URL", "redis://localhost:6379/0")
    namespace = os.getenv("SEED_REDIS_NAMESPACE", "seed")
    queue_name = os.getenv("SEED_WORKER_QUEUE", "q_batch")
    name = os.getenv("SEED_WORKER_NAME", f"worker-{queue_name}")

    db = DB(db_path)
    db.init_schema()

    pool = RedisPool(redis_url)
    r = pool.client()

    queuehub = RedisQueueHub(r=r, namespace=namespace)
    broker = RedisEventBroker(r=r, namespace=namespace)

    executor = InfrastructureActionExecutor()

    try:
        await worker_loop(
            name=name,
            queue_name=queue_name,
            db=db,
            queuehub=queuehub,
            broker=broker,
            executor=executor,
        )
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())



