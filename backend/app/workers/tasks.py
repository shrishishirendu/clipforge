"""Trivial tasks used to verify the queue/worker wiring end to end (BUILD_PLAN B3).
Real pipeline stages live in app/workers/pipeline.py."""
from __future__ import annotations


def ping() -> str:
    """Smallest possible job: enqueue it, run a worker, expect "pong" back."""
    return "pong"
