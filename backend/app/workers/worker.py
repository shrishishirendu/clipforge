"""Pipeline worker entrypoint (architecture §4.4):

    python -m app.workers.worker            # long-running: pull and run stage tasks
    python -m app.workers.worker --burst    # process what's queued, then exit

Workers are stateless and scale independently of the API tier (§8). On Windows
RQ's fork-based Worker is unavailable, so we use SimpleWorker (runs jobs in-process);
on POSIX we use the fork-based Worker for crash isolation.
"""
from __future__ import annotations

import argparse
import os

from rq import Queue, SimpleWorker, Worker
from rq.timeouts import TimerDeathPenalty

from app.workers.queue import QUEUE_NAME, get_redis


# On Windows RQ's fork-based Worker is unavailable and SIGALRM (its default job
# timeout) doesn't exist, so use SimpleWorker with a timer-based timeout. On POSIX
# the fork-based Worker gives per-job crash isolation (NFR-07).
class _WindowsWorker(SimpleWorker):
    death_penalty_class = TimerDeathPenalty


WorkerClass = _WindowsWorker if os.name == "nt" else Worker


def main() -> None:
    parser = argparse.ArgumentParser(description="ClipForge pipeline worker")
    parser.add_argument("--burst", action="store_true",
                        help="run queued jobs then exit (used for tests/CI)")
    args = parser.parse_args()

    connection = get_redis()
    queue = Queue(QUEUE_NAME, connection=connection)
    worker = WorkerClass([queue], connection=connection)
    worker.work(burst=args.burst)


if __name__ == "__main__":
    main()
