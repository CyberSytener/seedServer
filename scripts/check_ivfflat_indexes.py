import asyncio
import os

import asyncpg


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://seed:seed@postgres:5432/seed_server")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(
            """
            SELECT tablename, indexname, indexdef
            FROM pg_indexes
            WHERE tablename IN ('job_leads', 'user_skills', 'skill_embeddings')
              AND indexdef ILIKE '%ivfflat%'
            ORDER BY tablename, indexname
            """
        )
    finally:
        await conn.close()

    print("IVFFLAT indexes:")
    for row in rows:
        print(f"{row['tablename']}: {row['indexname']} -> {row['indexdef']}")


if __name__ == "__main__":
    asyncio.run(main())
