"""B6: clip-list review API — GET/PATCH /cliplist and POST /reedit
(FR-16, FR-17, FR-18; snap-to-silence FR-15; re-edit preserves locked segments)."""
import json

from sqlalchemy.orm import Session

from app.models.entities import ApprovalStatus, ClipList, JobStatus, Project
from app.workers.pipeline import run_reedit
from tests._doubles import FakeLLM, drive_to_review as _drive_to_review

# CANNED_TRANSCRIPT silence points are [0.0, 1.45, 2.4].


def test_get_cliplist_serves_segments_and_full_coverage(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)

    body = client.get(f"/api/projects/{pid}/cliplist").json()
    assert body["approval_status"] == "pending"
    assert len(body["segments"]) == 2
    assert [s["order"] for s in body["segments"]] == [0, 1]
    assert body["uncovered_key_point_ids"] == []          # both key points covered
    assert body["total_duration_sec"] == 2                 # round(1.45 + 0.95)


def test_get_cliplist_404_without_selection(client, make_project):
    pid = make_project()  # never started/selected
    assert client.get(f"/api/projects/{pid}/cliplist").status_code == 404


def test_patch_remove_updates_coverage_and_total(client, storage, db_engine, make_project):
    pid = make_project()
    kps = _drive_to_review(storage, db_engine, pid)
    segs = client.get(f"/api/projects/{pid}/cliplist").json()["segments"]
    second = segs[1]["id"]

    body = client.patch(f"/api/projects/{pid}/cliplist",
                        json={"edits": [{"segment_id": second, "remove": True}]}).json()
    assert len(body["segments"]) == 1
    assert kps["summary"] in body["uncovered_key_point_ids"]   # its key point now a gap
    assert body["total_duration_sec"] == 1                     # only the 1.45s segment


def test_patch_reorder_and_lock(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    segs = client.get(f"/api/projects/{pid}/cliplist").json()["segments"]
    first, second = segs[0]["id"], segs[1]["id"]

    body = client.patch(f"/api/projects/{pid}/cliplist", json={"edits": [
        {"segment_id": first, "order": 1, "locked": True},
        {"segment_id": second, "order": 0},
    ]}).json()
    by_id = {s["id"]: s for s in body["segments"]}
    assert by_id[second]["order"] == 0 and by_id[first]["order"] == 1
    assert by_id[first]["locked"] is True


def test_patch_nudge_snaps_to_silence(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    first = client.get(f"/api/projects/{pid}/cliplist").json()["segments"][0]["id"]

    # nudge end toward 2.3 -> snaps to the nearest silence point (2.4)
    body = client.patch(f"/api/projects/{pid}/cliplist",
                        json={"edits": [{"segment_id": first, "end_sec": 2.3}]}).json()
    moved = next(s for s in body["segments"] if s["id"] == first)
    assert moved["end_sec"] == 2.4


def test_patch_rejects_collapsed_segment(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    first = client.get(f"/api/projects/{pid}/cliplist").json()["segments"][0]["id"]
    # end nudged to 0.0 snaps to 0.0 -> end <= start
    r = client.patch(f"/api/projects/{pid}/cliplist",
                     json={"edits": [{"segment_id": first, "end_sec": 0.0}]})
    assert r.status_code == 422


def test_patch_unknown_segment_404(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    r = client.patch(f"/api/projects/{pid}/cliplist",
                     json={"edits": [{"segment_id": "nope", "remove": True}]})
    assert r.status_code == 404


def test_patch_blocked_after_approval(client, storage, db_engine, make_project):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    with Session(db_engine) as s:
        s.query(ClipList).filter_by(project_id=pid).one().approval_status = \
            ApprovalStatus.APPROVED
        s.commit()
    first = "x"
    r = client.patch(f"/api/projects/{pid}/cliplist",
                     json={"edits": [{"segment_id": first, "remove": True}]})
    assert r.status_code == 409


# --- re-edit ----------------------------------------------------------------

def test_reedit_enqueues_and_reopens(client, storage, db_engine, make_project, queue):
    pid = make_project()
    _drive_to_review(storage, db_engine, pid)
    r = client.post(f"/api/projects/{pid}/reedit")
    assert r.status_code == 202
    assert r.json()["status"] == "selecting"
    assert queue.count == 1
    assert queue.jobs[0].func_name == "app.workers.pipeline.reedit_stage"


def test_reedit_preserves_locked_segment(client, storage, db_engine, make_project):
    pid = make_project()
    kps = _drive_to_review(storage, db_engine, pid)

    # lock the first segment (covers the deck key point)
    with Session(db_engine) as s:
        clip = s.query(ClipList).filter_by(project_id=pid).one()
        seg_a = next(seg for seg in clip.segments if seg.start_sec == 0.0)
        seg_a.locked = True
        s.commit()

    # re-edit re-selects only the remaining (summary) key point
    resp = json.dumps({"segments": [
        {"start_sec": 1.45, "end_sec": 2.4, "transcript": "talk again",
         "key_point_id": kps["summary"], "confidence": 0.7}],
        "total_duration_sec": 0.95, "uncovered_key_point_ids": []})
    with Session(db_engine) as s:
        run_reedit(s, FakeLLM([resp]), pid)

    with Session(db_engine) as s:
        assert s.get(Project, pid).status == JobStatus.AWAITING_REVIEW
        clip = s.query(ClipList).filter_by(project_id=pid).one()
        by_kp = {seg.key_point_id: seg for seg in clip.segments}
        # locked deck segment preserved exactly; summary segment re-selected
        assert by_kp[kps["deck"]].locked is True
        assert by_kp[kps["deck"]].start_sec == 0.0 and by_kp[kps["deck"]].end_sec == 1.45
        assert by_kp[kps["summary"]].transcript_snippet == "talk again"
        assert by_kp[kps["summary"]].locked is False
