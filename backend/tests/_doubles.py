"""Shared test doubles for the pipeline (fake transcription, parsing, LLM, media)."""
import json
import os

from sqlalchemy.orm import Session

# A small canned transcript with silence points, reused across pipeline tests.
CANNED_TRANSCRIPT = {
    "full_text": "hello world this is a talk",
    "word_timings": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 0.9},
        {"word": "talk", "start": 2.0, "end": 2.4},
    ],
    "silence_points": [0.0, 1.45, 2.4],
}


class FakeTranscriptionProvider:
    def __init__(self, result=None):
        self.result = result or CANNED_TRANSCRIPT
        self.calls = []

    def transcribe(self, audio_uri, vocabulary):
        self.calls.append((audio_uri, list(vocabulary)))
        return self.result


class FakeDocumentParser:
    """Returns one key point per parsed asset, tagged with the asset type."""

    def __init__(self):
        self.calls = []

    def extract_key_points(self, path, asset_type, ext):
        self.calls.append((path, asset_type, ext))
        return [{"text": f"key point from {asset_type}", "source": asset_type}]


class FakeLLM:
    """Returns queued responses in order; records prompts for assertions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user, max_tokens=4000):
        self.calls.append((system, user))
        return self.responses.pop(0)


class FakeMediaEngine:
    """Writes a dummy MP4 to output_path instead of running FFmpeg."""

    def __init__(self):
        self.calls = []

    def render(self, source_path, segments, output_path, resolution="1080p"):
        self.calls.append((source_path, list(segments), resolution))
        with open(output_path, "wb") as fh:
            fh.write(b"FAKE-MP4-DATA")
        return {"size_bytes": os.path.getsize(output_path)}


def drive_to_review(storage, db_engine, pid):
    """Run transcribe + extract + select so `pid` reaches AWAITING_REVIEW with a
    two-segment clip list (one per key point). Returns {source: key_point_id}."""
    # imported here to avoid a heavy import when only the fakes are needed
    from app.workers.pipeline import run_extraction, run_selection, run_transcription
    from app.models.entities import KeyPoint

    with Session(db_engine) as s:
        run_transcription(s, storage, FakeTranscriptionProvider(), pid)
        run_extraction(s, storage, FakeDocumentParser(), pid)
    with Session(db_engine) as s:
        kps = {k.source: k.id for k in s.query(KeyPoint).filter_by(project_id=pid)}
    resp = json.dumps({"segments": [
        {"start_sec": 0.0, "end_sec": 1.45, "transcript": "hello world",
         "key_point_id": kps["deck"], "confidence": 0.9},
        {"start_sec": 1.45, "end_sec": 2.4, "transcript": "talk",
         "key_point_id": kps["summary"], "confidence": 0.8}],
        "total_duration_sec": 2.4, "uncovered_key_point_ids": []})
    with Session(db_engine) as s:
        run_selection(s, FakeLLM([resp]), pid)
    return kps
