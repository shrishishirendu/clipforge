"""B4: the upload -> transcribe -> store slice (FR-07, FR-09, FR-24, FR-25).

Hermetic: a fake TranscriptionProvider stands in for Whisper and a fake store
stands in for MinIO, so no model/video/Redis is needed. The real faster-whisper
path is exercised separately by a live verification run.
"""
from sqlalchemy.orm import Session

from app.models.entities import JobStatus, Project, Transcript
from app.services.transcription import LocalWhisperProvider
from app.workers.pipeline import run_transcription

CANNED = {
    "full_text": "hello world this is a talk",
    "word_timings": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 0.9},
        {"word": "talk", "start": 2.0, "end": 2.4},
    ],
    "silence_points": [0.0, 1.45, 2.4],
}


class FakeProvider:
    def __init__(self, result=None):
        self.result = result or CANNED
        self.calls = []

    def transcribe(self, audio_uri, vocabulary):
        self.calls.append((audio_uri, list(vocabulary)))
        return self.result


# --- helpers -----------------------------------------------------------------

def _complete_asset(client, storage, pid, atype, fname):
    up = client.post(f"/api/projects/{pid}/assets",
                     json={"type": atype, "filename": fname}).json()
    storage.simulate_upload(up["storage_uri"], size_bytes=4096)
    client.post(f"/api/projects/{pid}/assets/{up['asset_id']}/complete")
    return up


def _project_with_all_assets(client, storage, vocabulary=None):
    pid = client.post("/api/projects",
                      json={"title": "T", "vocabulary": vocabulary or []}).json()["id"]
    _complete_asset(client, storage, pid, "video", "talk.mp4")
    _complete_asset(client, storage, pid, "deck", "slides.pptx")
    _complete_asset(client, storage, pid, "summary", "notes.docx")
    return pid


# --- POST /start -------------------------------------------------------------

def test_start_requires_all_three_assets(client, storage):
    pid = client.post("/api/projects", json={"title": "T"}).json()["id"]
    _complete_asset(client, storage, pid, "video", "talk.mp4")  # only the video
    r = client.post(f"/api/projects/{pid}/start")
    assert r.status_code == 409
    assert "deck" in r.text and "summary" in r.text


def test_start_unknown_project_404(client):
    assert client.post("/api/projects/nope/start").status_code == 404


def test_start_enqueues_transcription(client, storage, queue):
    pid = _project_with_all_assets(client, storage)
    r = client.post(f"/api/projects/{pid}/start")
    assert r.status_code == 202
    assert r.json()["status"] == "transcribing"
    assert queue.count == 1
    assert queue.jobs[0].func_name == "app.workers.pipeline.transcribe_stage"
    assert queue.jobs[0].args == (pid,)


def test_start_twice_conflicts(client, storage):
    pid = _project_with_all_assets(client, storage)
    assert client.post(f"/api/projects/{pid}/start").status_code == 202
    assert client.post(f"/api/projects/{pid}/start").status_code == 409


# --- the stage itself --------------------------------------------------------

def test_run_transcription_persists_transcript(client, storage, db_engine):
    pid = _project_with_all_assets(client, storage, vocabulary=["Acme", "Kubernetes"])
    provider = FakeProvider()

    with Session(db_engine) as s:
        run_transcription(s, storage, provider, pid)

    with Session(db_engine) as s:
        t = s.query(Transcript).filter_by(project_id=pid).one()
        assert t.full_text == CANNED["full_text"]
        assert t.word_timings == CANNED["word_timings"]
        assert t.silence_points == CANNED["silence_points"]
        assert s.get(Project, pid).status == JobStatus.EXTRACTING

    # custom vocabulary was passed through to the provider (FR-08)
    assert provider.calls[0][1] == ["Acme", "Kubernetes"]


def test_run_transcription_is_idempotent(client, storage, db_engine):
    """Re-running replaces the transcript rather than duplicating it (NFR-07)."""
    pid = _project_with_all_assets(client, storage)
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeProvider(), pid)
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeProvider(), pid)
    with Session(db_engine) as s:
        assert s.query(Transcript).filter_by(project_id=pid).count() == 1


def test_run_transcription_marks_failed_on_error(client, storage, db_engine):
    pid = _project_with_all_assets(client, storage)

    class Boom:
        def transcribe(self, *a, **k):
            raise RuntimeError("model exploded")

    with Session(db_engine) as s:
        try:
            run_transcription(s, storage, Boom(), pid)
        except RuntimeError:
            pass
    with Session(db_engine) as s:
        assert s.get(Project, pid).status == JobStatus.FAILED
        assert s.query(Transcript).filter_by(project_id=pid).count() == 0


# --- GET /status -------------------------------------------------------------

def test_status_progresses_pending_then_done(client, storage, db_engine):
    pid = _project_with_all_assets(client, storage)

    stages = {s["name"]: s for s in client.get(f"/api/projects/{pid}/status").json()["stages"]}
    assert stages["transcription"]["state"] == "pending"

    with Session(db_engine) as s:
        run_transcription(s, storage, FakeProvider(), pid)

    body = client.get(f"/api/projects/{pid}/status").json()
    assert body["status"] == "extracting"
    stages = {s["name"]: s for s in body["stages"]}
    assert stages["transcription"]["state"] == "done"
    assert stages["transcription"]["pct"] == 100
    assert [s["name"] for s in body["stages"]] == \
        ["transcription", "extraction", "selection", "review", "render"]


# --- silence-point derivation (FR-09, FR-15), no model needed ----------------

def test_silence_points_from_word_gaps():
    p = LocalWhisperProvider(silence_gap_sec=0.4)
    words = [
        {"word": "a", "start": 0.0, "end": 0.5},
        {"word": "b", "start": 0.6, "end": 1.0},   # gap 0.1 -> ignored
        {"word": "c", "start": 1.8, "end": 2.2},   # gap 0.8 -> midpoint 1.4
    ]
    pts = p._silence_points(words)
    assert pts[0] == 0.0      # clip start
    assert 1.4 in pts         # gap midpoint
    assert pts[-1] == 2.2     # clip end


def test_silence_points_empty():
    assert LocalWhisperProvider(silence_gap_sec=0.4)._silence_points([]) == []
