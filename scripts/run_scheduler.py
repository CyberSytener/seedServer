import asyncio

import redis.asyncio as redis

from app.infrastructure.redis.queue import RedisQueueHub
from app.infrastructure.scheduler import scheduler_loop
from app.settings import get_settings


def main() -> None:
    settings = get_settings()
    r = redis.from_url(settings.redis_url, decode_responses=False)
    hub = RedisQueueHub(r=r, namespace=settings.redis_namespace)
    asyncio.run(scheduler_loop(queuehub=hub))


if __name__ == "__main__":
    main()
