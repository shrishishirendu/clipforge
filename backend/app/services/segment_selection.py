"""CORE IP — maps key points to transcript segments via the LLM (FR-12..15).

Contract (technical architecture §9):
  Input  : key points (id + text + source), a timestamped transcript (lines +
           silence boundaries), constraints (target duration, snap-to-silence).
  Output : STRICT JSON only — ordered segments + total + uncovered key points.
  Guards : parse strictly, re-prompt on bad JSON (bounded), snap boundaries to
           silence server-side (FR-15), flag (don't truncate) if over target (FR-14).

Read architecture §9 before modifying. The raw model call is behind LLMProvider
(Claude Sonnet by default, NFR-02); the prompt + validation + snapping are the IP.
"""
from __future__ import annotations

import json
import re

from app.services.interfaces import LLMProvider

_SYSTEM = """You are a video editor selecting the segments that best convey a \
talk's key points within a target duration. You receive key points and a \
timestamped transcript (lines with start_sec/end_sec) plus the allowed silence \
boundaries. Select segments that:
- cover as many key points as possible within the target duration,
- begin and end ONLY on the provided silence boundaries,
- read as coherent standalone clips.
For each segment set key_point_id to the id of the key point it covers.
Return ONLY valid JSON, no prose, no markdown fences, shaped exactly as:
{"segments":[{"start_sec":N,"end_sec":N,"transcript":"...","key_point_id":"kp-id","confidence":0.0}],
 "total_duration_sec":N,"uncovered_key_point_ids":["kp-id"]}"""


class SegmentSelectionError(Exception):
    pass


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def transcript_lines(transcript: dict) -> list[dict]:
    """Compact, token-efficient view for the LLM: word timings grouped into lines
    split at interior silence boundaries. Falls back to full_text if no words."""
    words = transcript.get("word_timings", [])
    if not words:
        return [{"start_sec": 0.0, "end_sec": 0.0,
                 "text": _collapse_ws(transcript.get("full_text", ""))}]

    splits = sorted(s for s in set(transcript.get("silence_points", []))
                    if words[0]["start"] < s < words[-1]["end"])
    lines, cur, si = [], [], 0
    for w in words:
        while si < len(splits) and w["start"] >= splits[si]:
            if cur:
                lines.append(cur)
                cur = []
            si += 1
        cur.append(w)
    if cur:
        lines.append(cur)

    return [{"start_sec": round(lw[0]["start"], 2),
             "end_sec": round(lw[-1]["end"], 2),
             "text": _collapse_ws(" ".join(x["word"] for x in lw))}
            for lw in lines]


def select_segments(key_points: list[dict], transcript: dict,
                    target_min: int, target_max: int,
                    llm: LLMProvider | None = None, max_retries: int = 2) -> dict:
    """Call the LLM for a clip list, validate strictly, snap to silence. Returns
    {"segments": [...], "total_duration_sec": N, "uncovered_key_point_ids": [...],
     "_over_target": bool}."""
    if llm is None:
        from app.services.llm import get_llm_provider
        llm = get_llm_provider()

    known_ids = {kp["id"] for kp in key_points}
    user = json.dumps({
        "key_points": key_points,
        "transcript": {"lines": transcript_lines(transcript),
                       "silence_points": sorted(set(transcript.get("silence_points", [])))},
        "constraints": {"target_min_sec": target_min, "target_max_sec": target_max,
                        "snap_to_silence": True},
    })

    last_err = None
    for _ in range(max_retries + 1):
        text = llm.complete(_SYSTEM, user)
        try:
            data = json.loads(_strip_fences(text))
            _validate(data, known_ids)
            return _snap_and_total(data, transcript, target_max)
        except (json.JSONDecodeError, SegmentSelectionError) as e:
            last_err = e
            user = (f"{user}\n\nYour previous output was invalid: {e}. "
                    "Return ONLY valid JSON in the required shape.")
    raise SegmentSelectionError(f"selection failed after retries: {last_err}")


def _strip_fences(text: str) -> str:
    """Defensive: strip ```json fences if the model adds them despite instructions."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
    return t.strip()


def _validate(data: dict, known_ids: set[str]) -> None:
    if not isinstance(data.get("segments"), list):
        raise SegmentSelectionError("missing or non-list 'segments'")
    for seg in data["segments"]:
        s, e = seg.get("start_sec"), seg.get("end_sec")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)) or e <= s:
            raise SegmentSelectionError(f"bad segment bounds: {seg}")
        kp = seg.get("key_point_id")
        if kp is not None and kp not in known_ids:
            raise SegmentSelectionError(f"unknown key_point_id: {kp}")


def snap_to_silence(value: float, silence: list[float]) -> float:
    """Snap a timestamp to the nearest silence boundary (FR-15). Used by selection
    and by reviewer boundary nudges (B6)."""
    return min(silence, key=lambda s: abs(s - value)) if silence else value


def _snap_and_total(data: dict, transcript: dict, target_max: int) -> dict:
    """Snap every boundary to the nearest silence point (FR-15), drop any segment
    that collapses, recompute the total, and flag (don't truncate) if over (FR-14)."""
    silence = sorted(set(transcript.get("silence_points", [])))
    snapped, total = [], 0.0
    for seg in data["segments"]:
        s = round(snap_to_silence(seg["start_sec"], silence), 3)
        e = round(snap_to_silence(seg["end_sec"], silence), 3)
        if e <= s:
            continue  # boundary collapsed onto one point — drop it
        seg = {**seg, "start_sec": s, "end_sec": e,
               "confidence": max(0.0, min(1.0, float(seg.get("confidence", 0.0))))}
        snapped.append(seg)
        total += e - s

    data["segments"] = snapped
    data["total_duration_sec"] = round(total, 1)
    data["_over_target"] = total > target_max
    data.setdefault("uncovered_key_point_ids", [])
    return data
