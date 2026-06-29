"""RQ queue wiring. A single durable queue decouples the API tier from the heavy
pipeline workers (architecture §8): the orchestrator enqueues stage tasks here and
workers (app/workers/worker.py) pull and run them. A worker crash returns the task
to the queue rather than losing the job (NFR-07)."""
from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.core.config import settings

QUEUE_NAME = "clipforge"


@lru_cache
def get_redis() -> Redis:
    """Process-wide Redis connection built from settings.redis_url."""
    return Redis.from_url(settings.redis_url)


@lru_cache
def get_queue() -> Queue:
    """The default work queue (architecture §8)."""
    return Queue(QUEUE_NAME, connection=get_redis())
