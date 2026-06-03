import asyncio
import os
import random
import time
from typing import List

import asyncpg


DIMENSIONS = 1536
TOTAL_EMBEDDINGS = 1000
CONCURRENT_QUERIES = 100
ENTITY_TYPE = "benchmark_skill"
MODEL_NAME = "bench-embedding"
DEFAULT_PROBES = 10
DEFAULT_LISTS = 100


def _vector_literal(values: List[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def _make_embedding() -> List[float]:
    return [random.random() for _ in range(DIMENSIONS)]


async def _insert_embeddings(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM skill_embeddings WHERE entity_type = $1",
            ENTITY_TYPE,
        )

    for offset in range(0, TOTAL_EMBEDDINGS, 100):
        batch = []
        for idx in range(offset, min(offset + 100, TOTAL_EMBEDDINGS)):
            embedding = _vector_literal(_make_embedding())
            batch.append(
                (
                    ENTITY_TYPE,
                    f"bench_{idx}",
                    f"benchmark skill {idx}",
                    embedding,
                    MODEL_NAME,
                )
            )

        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO skill_embeddings (entity_type, entity_id, text, embedding, model)
                VALUES ($1, $2, $3, $4::vector, $5)
                ON CONFLICT (entity_type, entity_id) DO UPDATE
                SET text = EXCLUDED.text,
                    embedding = EXCLUDED.embedding,
                    model = EXCLUDED.model,
                    created_at = NOW()
                """,
                batch,
            )


async def _run_query(pool: asyncpg.Pool, embedding: str, probes: int) -> float:
    start = time.perf_counter()
    safe_probes = int(probes)
    async with pool.acquire() as conn:
        await conn.execute(f"SET ivfflat.probes = {safe_probes}")
        await conn.fetch(
            """
            SELECT entity_id, 1 - (embedding <=> $1::vector) AS similarity
            FROM skill_embeddings
            WHERE entity_type = $2
            ORDER BY embedding <=> $1::vector
            LIMIT 5
            """,
            embedding,
            ENTITY_TYPE,
        )
    return (time.perf_counter() - start) * 1000


def _p99_ms(latencies: List[float]) -> float:
    if not latencies:
        return 0.0
    sorted_vals = sorted(latencies)
    index = int((len(sorted_vals) - 1) * 0.99)
    return sorted_vals[index]


async def _recreate_ivfflat_index(conn: asyncpg.Connection, lists: int) -> None:
    safe_lists = int(lists)
    await conn.execute("DROP INDEX IF EXISTS ix_skill_embeddings_ann")
    await conn.execute(
        "CREATE INDEX ix_skill_embeddings_ann "
        "ON skill_embeddings USING ivfflat (embedding vector_cosine_ops) "
        f"WITH (lists = {safe_lists})"
    )


def _parse_int_list(raw: str, default: List[int]) -> List[int]:
    if not raw:
        return default
    values: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        values.append(int(part))
    return values or default


async def _benchmark(pool: asyncpg.Pool, probes: int) -> List[float]:
    queries = []
    for _ in range(CONCURRENT_QUERIES):
        queries.append(_run_query(pool, _vector_literal(_make_embedding()), probes))
    return await asyncio.gather(*queries)


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://seed:seed@postgres:5432/seed_server")
    sweep = os.getenv("SWEEP_IVFFLAT", "0") == "1"
    probes_values = _parse_int_list(os.getenv("IVFFLAT_PROBES", ""), [DEFAULT_PROBES])
    lists_values = _parse_int_list(os.getenv("IVFFLAT_LISTS", ""), [DEFAULT_LISTS])
    recreate_index = os.getenv("RECREATE_IVFFLAT_INDEX", "0") == "1"
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=20)
    try:
        await _insert_embeddings(pool)

        if sweep:
            print(f"Total embeddings: {TOTAL_EMBEDDINGS}")
            print(f"Concurrent queries: {CONCURRENT_QUERIES}")
            baseline_p50 = None
            baseline_p99 = None
            for lists in lists_values:
                async with pool.acquire() as conn:
                    if recreate_index:
                        await _recreate_ivfflat_index(conn, lists)

                for probes in probes_values:
                    latencies = await _benchmark(pool, probes)
                    p99 = _p99_ms(latencies)
                    p50 = sorted(latencies)[len(latencies) // 2]
                    if baseline_p50 is None:
                        baseline_p50 = p50
                        baseline_p99 = p99
                    p50_delta = p50 - baseline_p50
                    p99_delta = p99 - baseline_p99
                    print(
                        "lists={lists} probes={probes} "
                        "p50={p50:.2f}ms (delta {p50_delta:+.2f}) "
                        "p99={p99:.2f}ms (delta {p99_delta:+.2f})".format(
                            lists=lists,
                            probes=probes,
                            p50=p50,
                            p50_delta=p50_delta,
                            p99=p99,
                            p99_delta=p99_delta,
                        )
                    )
            return

        probes = probes_values[0]
        lists = lists_values[0]
        if recreate_index:
            async with pool.acquire() as conn:
                await _recreate_ivfflat_index(conn, lists)

        latencies = await _benchmark(pool, probes)

        p99 = _p99_ms(latencies)
        avg = sum(latencies) / len(latencies)
        p50 = sorted(latencies)[len(latencies) // 2]

        print(f"Total embeddings: {TOTAL_EMBEDDINGS}")
        print(f"Concurrent queries: {CONCURRENT_QUERIES}")
        print(f"IVFFlat lists: {lists}")
        print(f"IVFFlat probes: {probes}")
        print(f"Average latency: {avg:.2f} ms")
        print(f"p50 latency: {p50:.2f} ms")
        print(f"p99 latency: {p99:.2f} ms")
        if p99 > 50:
            print("\nTuning suggestion: consider increasing ivfflat lists (index) or probes for better recall/latency tradeoff.")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
