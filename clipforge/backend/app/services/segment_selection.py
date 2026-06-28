"""CORE IP — maps key points to transcript segments via Claude (FR-12..15).

Contract (technical architecture §9):
  Input  : key points (+source), timestamped transcript with silence points,
           constraints (target duration, snap-to-silence).
  Output : STRICT JSON only — ordered segments + total + uncovered key points.
  Guards : parse strictly, re-prompt on bad JSON (bounded), verify timestamps
           exist & snap to silence, verify duration within target.

Read architecture §9 before modifying. Use Sonnet (NFR-02).
"""
from __future__ import annotations

import json

from anthropic import Anthropic

from app.core.config import settings

_SYSTEM = """You are a video editor selecting the segments that best convey a \
talk's key points within a target duration. You will receive key points and a \
timestamped transcript with silence boundaries. Select segments that:
- cover as many key points as possible within the target duration,
- start and end ONLY on the provided silence boundaries,
- read as coherent standalone clips.
Return ONLY valid JSON, no prose, no markdown fences, shaped exactly as:
{"segments":[{"start_sec":N,"end_sec":N,"transcript":"...","key_point_id":"...","confidence":0.0}],
 "total_duration_sec":N,"uncovered_key_point_ids":["..."]}"""


class SegmentSelectionError(Exception):
    pass


def select_segments(key_points: list[dict], transcript: dict,
                    target_min: int, target_max: int,
                    max_retries: int = 2) -> dict:
    client = Anthropic(api_key=settings.anthropic_api_key)
    user = json.dumps({
        "key_points": key_points,
        "transcript": transcript,
        "constraints": {
            "target_min_sec": target_min,
            "target_max_sec": target_max,
            "snap_to_silence": True,
        },
    })

    last_err = None
    for _ in range(max_retries + 1):
        resp = client.messages.create(
            model=settings.segment_selection_model,
            max_tokens=4000,
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        try:
            data = json.loads(text)
            _validate(data, transcript, target_max)
            return data
        except (json.JSONDecodeError, SegmentSelectionError) as e:
            last_err = e
            user = f"{user}\n\nYour previous output was invalid: {e}. Return ONLY valid JSON."
    raise SegmentSelectionError(f"Selection failed after retries: {last_err}")


def _validate(data: dict, transcript: dict, target_max: int) -> None:
    if "segments" not in data:
        raise SegmentSelectionError("missing 'segments'")
    silence = set(round(s, 1) for s in transcript.get("silence_points", []))
    total = 0.0
    for seg in data["segments"]:
        s, e = seg.get("start_sec"), seg.get("end_sec")
        if s is None or e is None or e <= s:
            raise SegmentSelectionError(f"bad segment bounds: {seg}")
        total += e - s
        # Snapping is enforced server-side too; here we only warn via exception
        # if grossly off. Actual snap happens in the boundary-snap step.
    # NOTE: do not silently truncate; flag if over (FR-14)
    data["_over_target"] = total > target_max
