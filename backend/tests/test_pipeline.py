"""B5: pipeline orchestration — extraction, parallel-then-converge, and selection
ending at the approval gate (arch §6, FR-12..15, FR-19)."""
import json

from sqlalchemy.orm import Session

from app.models.entities import (
    ApprovalStatus, ClipList, JobStatus, KeyPoint, Project, Segment,
)
from app.workers.pipeline import (
    maybe_enqueue_selection, run_extraction, run_selection, run_transcription,
)
from tests._doubles import FakeDocumentParser, FakeLLM, FakeTranscriptionProvider


def _set_status(db_engine, pid, status):
    with Session(db_engine) as s:
        s.get(Project, pid).status = status
        s.commit()


def test_run_extraction_persists_key_points(make_project, storage, db_engine):
    pid = make_project()
    with Session(db_engine) as s:
        run_extraction(s, storage, FakeDocumentParser(), pid)
    with Session(db_engine) as s:
        kps = s.query(KeyPoint).filter_by(project_id=pid).all()
        assert len(kps) == 2  # one each from deck + summary
        assert {k.source for k in kps} == {"deck", "summary"}


def test_extraction_idempotent(make_project, storage, db_engine):
    pid = make_project()
    for _ in range(2):
        with Session(db_engine) as s:
            run_extraction(s, storage, FakeDocumentParser(), pid)
    with Session(db_engine) as s:
        assert s.query(KeyPoint).filter_by(project_id=pid).count() == 2


def test_converge_enqueues_selection_only_when_both_present(make_project, storage,
                                                            db_engine, queue):
    pid = make_project()
    _set_status(db_engine, pid, JobStatus.TRANSCRIBING)

    # transcript only -> no convergence yet
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeTranscriptionProvider(), pid)
        assert maybe_enqueue_selection(s, queue, pid) is False
    assert queue.count == 0

    # key points land too -> selection enqueued exactly once
    with Session(db_engine) as s:
        run_extraction(s, storage, FakeDocumentParser(), pid)
        assert maybe_enqueue_selection(s, queue, pid) is True
    assert queue.count == 1
    assert queue.jobs[0].func_name == "app.workers.pipeline.select_segments_stage"
    assert queue.jobs[0].args == (pid,)

    # idempotent: status is now SELECTING, so it won't enqueue again
    with Session(db_engine) as s:
        assert maybe_enqueue_selection(s, queue, pid) is False
    assert queue.count == 1


def test_run_selection_persists_clip_list_and_awaits_review(make_project, storage,
                                                            db_engine):
    pid = make_project()
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeTranscriptionProvider(), pid)
        run_extraction(s, storage, FakeDocumentParser(), pid)
    with Session(db_engine) as s:
        kp_id = s.query(KeyPoint).filter_by(project_id=pid).first().id

    resp = json.dumps({"segments": [
        {"start_sec": 0.0, "end_sec": 2.0, "transcript": "hello world",
         "key_point_id": kp_id, "confidence": 0.8}],
        "total_duration_sec": 2.0, "uncovered_key_point_ids": []})

    with Session(db_engine) as s:
        run_selection(s, FakeLLM([resp]), pid)

    with Session(db_engine) as s:
        assert s.get(Project, pid).status == JobStatus.AWAITING_REVIEW  # the gate (FR-19)
        clip = s.query(ClipList).filter_by(project_id=pid).one()
        assert clip.approval_status == ApprovalStatus.PENDING
        segs = s.query(Segment).filter_by(clip_list_id=clip.id).all()
        assert len(segs) == 1 and segs[0].key_point_id == kp_id


def test_run_selection_marks_failed_on_bad_output(make_project, storage, db_engine):
    pid = make_project()
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeTranscriptionProvider(), pid)
        run_extraction(s, storage, FakeDocumentParser(), pid)

    with Session(db_engine) as s:
        try:
            run_selection(s, FakeLLM(["nonsense", "still bad", "nope"]), pid)
        except Exception:
            pass
    with Session(db_engine) as s:
        assert s.get(Project, pid).status == JobStatus.FAILED
        assert s.query(ClipList).filter_by(project_id=pid).count() == 0


def test_status_reaches_awaiting_review(make_project, storage, db_engine, client):
    pid = make_project()
    with Session(db_engine) as s:
        run_transcription(s, storage, FakeTranscriptionProvider(), pid)
        run_extraction(s, storage, FakeDocumentParser(), pid)
        kp_id = s.query(KeyPoint).filter_by(project_id=pid).first().id
    resp = json.dumps({"segments": [
        {"start_sec": 0.0, "end_sec": 2.0, "transcript": "hi",
         "key_point_id": kp_id, "confidence": 0.7}],
        "total_duration_sec": 2.0, "uncovered_key_point_ids": []})
    with Session(db_engine) as s:
        run_selection(s, FakeLLM([resp]), pid)

    body = client.get(f"/api/projects/{pid}/status").json()
    assert body["status"] == "awaiting_review"
    stages = {st["name"]: st["state"] for st in body["stages"]}
    assert stages["transcription"] == "done"
    assert stages["extraction"] == "done"
    assert stages["selection"] == "done"
    assert stages["review"] == "running"
