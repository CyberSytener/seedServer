import argparse
import asyncio
import os

import redis.asyncio as redis

from app.infrastructure.db.sqlite import DB
from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.redis.sse import RedisEventBroker
from app.settings import get_settings
from app.infrastructure.redis.worker import worker_loop
from app.infrastructure.llm.action_executor import InfrastructureActionExecutor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", required=True, help="Queue name (e.g. q_fast,q_batch,q_low)")
    parser.add_argument("--name", default="worker", help="Worker name for logs")
    args = parser.parse_args()

    settings = get_settings()
    db = DB(settings.db_path)
    db.init_schema()

    r = redis.from_url(settings.redis_url, decode_responses=False)
    hub = RedisQueueHub(r=r, namespace=settings.redis_namespace)
    broker = RedisEventBroker(r=r, namespace=settings.redis_namespace)

    executor = InfrastructureActionExecutor()

    # worker_loop signature: (name, queue_name, db, queuehub, broker, executor)
    asyncio.run(
        worker_loop(
            name=args.name,
            queue_name=args.queue,
            db=db,
            queuehub=hub,
            broker=broker,
            executor=executor,
        )
    )


if __name__ == "__main__":
    main()

