"""B5: the core IP — segment selection contract (arch §9, FR-12..15).
Uses a FakeLLM, so no API key/network is needed."""
import json

import pytest

from app.services.segment_selection import (
    SegmentSelectionError, select_segments, transcript_lines,
)
from tests._doubles import FakeLLM

TRANSCRIPT = {
    "full_text": "a b c d e f",
    "word_timings": [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.6, "end": 1.0},
        {"word": "c", "start": 2.0, "end": 2.5},
        {"word": "d", "start": 2.6, "end": 3.0},
        {"word": "e", "start": 5.0, "end": 5.5},
        {"word": "f", "start": 5.6, "end": 6.0},
    ],
    "silence_points": [0.0, 1.5, 4.0, 6.0],
}
KEY_POINTS = [{"id": "kp-1", "text": "point one", "source": "Slide 1"},
              {"id": "kp-2", "text": "point two", "source": "Summary"}]


def _resp(segments, total, uncovered=()):
    return json.dumps({"segments": segments, "total_duration_sec": total,
                       "uncovered_key_point_ids": list(uncovered)})


def test_transcript_lines_split_on_interior_silence():
    lines = transcript_lines(TRANSCRIPT)
    assert [ln["text"] for ln in lines] == ["a b", "c d", "e f"]
    assert lines[0]["start_sec"] == 0.0 and lines[0]["end_sec"] == 1.0


def test_snaps_boundaries_to_silence_and_recomputes_total():
    resp = _resp([{"start_sec": 0.1, "end_sec": 3.9, "transcript": "a b c d",
                   "key_point_id": "kp-1", "confidence": 0.9}], 3.8, ["kp-2"])
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 10, llm=FakeLLM([resp]))
    seg = out["segments"][0]
    assert seg["start_sec"] == 0.0   # snapped from 0.1
    assert seg["end_sec"] == 4.0     # snapped from 3.9
    assert out["total_duration_sec"] == 4.0
    assert out["_over_target"] is False
    assert out["uncovered_key_point_ids"] == ["kp-2"]


def test_flags_over_target_without_truncating():
    resp = _resp([{"start_sec": 0.0, "end_sec": 6.0, "transcript": "...",
                   "key_point_id": "kp-1", "confidence": 0.5}], 6.0)
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 3, llm=FakeLLM([resp]))  # max 3s
    assert out["_over_target"] is True
    assert len(out["segments"]) == 1   # not truncated (FR-14)


def test_drops_segment_that_collapses_after_snapping():
    # both bounds snap to the same silence point (6.0) -> dropped
    resp = _resp([{"start_sec": 5.9, "end_sec": 6.0, "transcript": "f",
                   "key_point_id": "kp-1", "confidence": 0.4}], 0.1)
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 10, llm=FakeLLM([resp]))
    assert out["segments"] == []


def test_reprompts_on_bad_json_then_succeeds():
    good = _resp([{"start_sec": 0.0, "end_sec": 4.0, "transcript": "x",
                   "key_point_id": None, "confidence": 0.5}], 4.0)
    llm = FakeLLM(["not json at all", good])
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 10, llm=llm, max_retries=2)
    assert len(out["segments"]) == 1
    assert len(llm.calls) == 2   # retried once


def test_rejects_unknown_key_point_id_after_retries():
    bad = _resp([{"start_sec": 0.0, "end_sec": 4.0, "transcript": "x",
                  "key_point_id": "kp-999", "confidence": 0.5}], 4.0)
    with pytest.raises(SegmentSelectionError):
        select_segments(KEY_POINTS, TRANSCRIPT, 2, 10,
                        llm=FakeLLM([bad, bad, bad]), max_retries=2)


def test_strips_code_fences():
    good = _resp([{"start_sec": 0.0, "end_sec": 4.0, "transcript": "x",
                   "key_point_id": "kp-1", "confidence": 0.5}], 4.0)
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 10,
                          llm=FakeLLM([f"```json\n{good}\n```"]))
    assert out["segments"][0]["start_sec"] == 0.0


def test_clamps_confidence():
    resp = _resp([{"start_sec": 0.0, "end_sec": 4.0, "transcript": "x",
                   "key_point_id": "kp-1", "confidence": 5.0}], 4.0)
    out = select_segments(KEY_POINTS, TRANSCRIPT, 2, 10, llm=FakeLLM([resp]))
    assert out["segments"][0]["confidence"] == 1.0
