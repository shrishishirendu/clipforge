"""Sidecar SRT caption generation (FR-21, OQ-03 → sidecar .srt).

Captions are built from the approved segments against the *output* timeline (the
concatenated cut), not the source timeline — each segment plays back-to-back.
"""
from __future__ import annotations


def _ts(seconds: float) -> str:
    """Seconds → SRT timestamp HH:MM:SS,mmm."""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_srt(segments: list[dict]) -> str:
    """Build an SRT document from segments (in output order). Each entry's text is
    the segment's transcript snippet, timed cumulatively along the rendered cut."""
    blocks, cursor = [], 0.0
    for i, seg in enumerate(segments, start=1):
        duration = seg["end_sec"] - seg["start_sec"]
        start, end = cursor, cursor + duration
        cursor = end
        text = (seg.get("transcript") or seg.get("transcript_snippet") or "").strip()
        blocks.append(f"{i}\n{_ts(start)} --> {_ts(end)}\n{text}\n")
    return "\n".join(blocks)
