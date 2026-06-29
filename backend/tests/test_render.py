"""B7: the approval gate, render, and output (FR-19, FR-20, FR-21, FR-23, NFR-07)."""
import pytest
from sqlalchemy.orm import Session

from app.models.entities import ApprovalStatus, ClipList, JobStatus, Project, RenderJob
from app.services.captions import build_srt
from app.workers.pipeline import run_render
from tests._doubles import FakeMediaEngine, drive_to_review


def _remove_one_segment(client, pid):
    segs = client.get(f"/api/projects/{pid}/cliplist").json()["segments"]
    client.patch(f"/api/projects/{pid}/cliplist",
                 json={"edits": [{"segment_id": segs[1]["id"], "remove": True}]})


# --- the approval gate (FR-19) ----------------------------------------------

def test_approve_enqueues_render_when_fully_covered(client, storage, db_engine,
                                                    make_project, queue):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)

    r = client.post(f"/api/projects/{pid}/approve")
    assert r.status_code == 202
    assert r.json()["status"] == "rendering"
    assert queue.count == 1
    assert queue.jobs[0].func_name == "app.workers.pipeline.render_stage"
    with Session(db_engine) as s:
        assert s.query(ClipList).filter_by(project_id=pid).one().approval_status == \
            ApprovalStatus.APPROVED


def test_approve_with_gaps_blocked_then_confirmed(client, storage, db_engine,
                                                  make_project, queue):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)
    _remove_one_segment(client, pid)  # leaves one key point uncovered

    blocked = client.post(f"/api/projects/{pid}/approve")
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["error"] == "uncovered_key_points"
    assert len(detail["uncovered_key_point_ids"]) == 1

    ok = client.post(f"/api/projects/{pid}/approve", json={"confirm_gaps": True})
    assert ok.status_code == 202
    assert queue.count == 1  # render enqueued only after confirmation


def test_approve_twice_conflicts(client, storage, db_engine, make_project):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)
    assert client.post(f"/api/projects/{pid}/approve").status_code == 202
    assert client.post(f"/api/projects/{pid}/approve").status_code == 409


def test_approve_empty_clip_list_422(client, storage, db_engine, make_project):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)
    # remove both segments
    segs = client.get(f"/api/projects/{pid}/cliplist").json()["segments"]
    client.patch(f"/api/projects/{pid}/cliplist",
                 json={"edits": [{"segment_id": s["id"], "remove": True} for s in segs]})
    assert client.post(f"/api/projects/{pid}/approve").status_code == 422


def test_approve_404_without_clip_list(client, make_project):
    pid = make_project()
    assert client.post(f"/api/projects/{pid}/approve").status_code == 404


# --- render (FR-20, FR-23) ; render never runs without approval (FR-19) -----

def test_run_render_refuses_unapproved(client, storage, db_engine, make_project):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)  # clip is PENDING, not approved
    with Session(db_engine) as s:
        with pytest.raises(ValueError):
            run_render(s, storage, FakeMediaEngine(), pid)
    with Session(db_engine) as s:
        assert s.get(Project, pid).status != JobStatus.COMPLETE
        assert s.query(RenderJob).filter_by(project_id=pid).count() == 0


def test_run_render_persists_output_and_completes(client, storage, db_engine, make_project):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)
    client.post(f"/api/projects/{pid}/approve")  # gate -> APPROVED + RENDERING

    with Session(db_engine) as s:
        run_render(s, storage, FakeMediaEngine(), pid)

    with Session(db_engine) as s:
        assert s.get(Project, pid).status == JobStatus.COMPLETE
        job = s.query(RenderJob).filter_by(project_id=pid).one()
        assert job.status == "complete"
        assert job.output_uri == f"projects/{pid}/output/cut.mp4"
        assert job.caption_uri == f"projects/{pid}/output/cut.srt"
        assert job.size_bytes > 0
    # both outputs were uploaded to storage
    assert f"projects/{pid}/output/cut.mp4" in storage.objects
    assert f"projects/{pid}/output/cut.srt" in storage.objects


# --- output (FR-23) ---------------------------------------------------------

def test_get_output_returns_download_links(client, storage, db_engine, make_project):
    pid = make_project()
    drive_to_review(storage, db_engine, pid)
    client.post(f"/api/projects/{pid}/approve")
    with Session(db_engine) as s:
        run_render(s, storage, FakeMediaEngine(), pid)

    body = client.get(f"/api/projects/{pid}/output").json()
    assert body["status"] == "complete"
    assert body["resolution"] == "1080p"
    assert body["size_bytes"] > 0
    assert body["video_url"].endswith("cut.mp4?sig=test&ttl=3600")
    assert body["captions_url"].endswith("cut.srt?sig=test&ttl=3600")


def test_get_output_404_before_render(client, make_project):
    pid = make_project()
    assert client.get(f"/api/projects/{pid}/output").status_code == 404


# --- sidecar SRT (FR-21) ----------------------------------------------------

def test_build_srt_cumulative_timeline():
    segments = [
        {"start_sec": 10.0, "end_sec": 12.0, "transcript": "first"},
        {"start_sec": 30.0, "end_sec": 31.5, "transcript": "second"},
    ]
    srt = build_srt(segments)
    assert "1\n00:00:00,000 --> 00:00:02,000\nfirst" in srt
    # second clip starts where the first ended (output timeline), not at 30s
    assert "2\n00:00:02,000 --> 00:00:03,500\nsecond" in srt
