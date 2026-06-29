"""API routes — indicative surface from architecture §7. Stubs raise
NotImplementedError; Claude Code fills these in per BUILD_PLAN.md."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from rq import Queue
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import (
    ApprovalStatus, AssetStatus, AssetType, ClipList, JobStatus, KeyPoint,
    MediaAsset, Project, Transcript,
)
from app.schemas.api import (
    AssetOut, AssetUploadRequest, AssetUploadResponse,
    ProjectCreate, ProjectOut, ClipListOut, ClipListPatch, SegmentOut, StatusOut,
)
from app.services.interfaces import ObjectStorage
from app.services.segment_selection import snap_to_silence
from app.services.storage import get_storage
from app.workers.pipeline import extract_stage, reedit_stage, transcribe_stage
from app.workers.queue import get_queue

router = APIRouter()

# Auth arrives at the gateway in Phase 5 (NFR-05); until then projects share one owner.
DEMO_OWNER = "demo-user"

# Accepted upload formats per asset type (FR-01, FR-02, FR-03).
ALLOWED_EXT: dict[AssetType, set[str]] = {
    AssetType.VIDEO: {"mp4", "mov"},
    AssetType.DECK: {"pptx", "pdf"},
    AssetType.SUMMARY: {"docx", "pdf", "txt"},
}
# Upper bounds enforced at the complete callback against the real object size (FR-04).
MAX_BYTES: dict[AssetType, int] = {
    AssetType.VIDEO: 2 * 1024 ** 3,    # 2 GiB
    AssetType.DECK: 100 * 1024 ** 2,   # 100 MiB
    AssetType.SUMMARY: 25 * 1024 ** 2,  # 25 MiB
}
UPLOAD_URL_TTL_SEC = 3600


def _asset_out(a: MediaAsset) -> AssetOut:
    return AssetOut(
        id=a.id, project_id=a.project_id, type=a.type.value,
        status=a.status.value, format=a.format, size_bytes=a.size_bytes,
        storage_uri=a.storage_uri,
    )


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project (FR-01..06). Assets are uploaded via POST /assets next."""
    if body.target_min_sec > body.target_max_sec:
        raise HTTPException(422, "target_min_sec must not exceed target_max_sec")
    project = Project(
        title=body.title,
        owner_id=DEMO_OWNER,
        target_min_sec=body.target_min_sec,
        target_max_sec=body.target_max_sec,
        vocabulary=body.vocabulary,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut(id=project.id, title=project.title, status=project.status.value)


@router.post("/projects/{project_id}/assets", response_model=AssetUploadResponse,
             status_code=201)
def register_asset(project_id: str, body: AssetUploadRequest,
                   db: Session = Depends(get_db),
                   storage: ObjectStorage = Depends(get_storage)):
    """Issue a presigned PUT URL for one asset and record it as PENDING (FR-01..04).
    The client uploads directly to storage, then calls .../complete."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "project not found")
    try:
        asset_type = AssetType(body.type)
    except ValueError:
        raise HTTPException(422, f"invalid asset type '{body.type}'")
    ext = body.filename.rsplit(".", 1)[-1].lower() if "." in body.filename else ""
    if ext not in ALLOWED_EXT[asset_type]:
        raise HTTPException(
            422,
            f"{asset_type.value} must be one of "
            f"{sorted(ALLOWED_EXT[asset_type])}; got '.{ext}'",
        )

    asset = MediaAsset(project_id=project_id, type=asset_type, storage_uri="",
                       format=ext, status=AssetStatus.PENDING)
    db.add(asset)
    db.flush()  # populate asset.id so it can key the object
    asset.storage_uri = f"projects/{project_id}/{asset_type.value}/{asset.id}.{ext}"
    db.commit()
    db.refresh(asset)

    url = storage.presigned_put_url(asset.storage_uri, expires_in=UPLOAD_URL_TTL_SEC)
    return AssetUploadResponse(
        asset_id=asset.id, type=asset_type.value, storage_uri=asset.storage_uri,
        upload_url=url, expires_in=UPLOAD_URL_TTL_SEC,
    )


@router.post("/projects/{project_id}/assets/{asset_id}/complete",
             response_model=AssetOut)
def complete_asset(project_id: str, asset_id: str,
                   db: Session = Depends(get_db),
                   storage: ObjectStorage = Depends(get_storage)):
    """Asset-complete callback: confirm the upload landed in storage, record its
    real size, and mark it READY (FR-04). Idempotent."""
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.project_id != project_id:
        raise HTTPException(404, "asset not found")

    info = storage.stat(asset.storage_uri)
    if info is None:
        raise HTTPException(409, "upload not found in storage; PUT the file first")
    if info["size_bytes"] > MAX_BYTES[asset.type]:
        raise HTTPException(
            413,
            f"{asset.type.value} exceeds max size {MAX_BYTES[asset.type]} bytes",
        )

    asset.size_bytes = info["size_bytes"]
    asset.status = AssetStatus.READY
    db.commit()
    db.refresh(asset)
    return _asset_out(asset)


REQUIRED_ASSET_TYPES = {AssetType.VIDEO, AssetType.DECK, AssetType.SUMMARY}

# Stages surfaced to the processing screen (FR-24). B4 implements transcription;
# later tasks fill in the rest. Listed so the frontend stepper (F2) has the shape.
PIPELINE_STAGES = ["transcription", "extraction", "selection", "review", "render"]
_STAGE_PCT = {"done": 100, "running": 50, "pending": 0, "failed": 0}


def _build_stages(status: JobStatus, has_transcript: bool,
                  has_key_points: bool, has_clip_list: bool) -> list[dict]:
    failed = status == JobStatus.FAILED
    processing = status in (JobStatus.TRANSCRIBING, JobStatus.EXTRACTING)

    def parallel_state(done: bool) -> str:
        # transcription/extraction run together during the processing phase
        return "done" if done else "failed" if failed else "running" if processing else "pending"

    states = {
        "transcription": parallel_state(has_transcript),
        "extraction": parallel_state(has_key_points),
        "selection": ("done" if has_clip_list else
                      "running" if status == JobStatus.SELECTING else
                      "failed" if failed else "pending"),
        "review": ("done" if status in (JobStatus.RENDERING, JobStatus.COMPLETE) else
                   "running" if status == JobStatus.AWAITING_REVIEW else "pending"),
        "render": ("done" if status == JobStatus.COMPLETE else
                   "running" if status == JobStatus.RENDERING else "pending"),
    }
    return [{"name": s, "state": states[s], "pct": _STAGE_PCT[states[s]]}
            for s in PIPELINE_STAGES]


@router.post("/projects/{project_id}/start", status_code=202)
def start_processing(project_id: str, db: Session = Depends(get_db),
                     queue: Queue = Depends(get_queue)):
    """Begin processing once all three assets are present and READY (FR-04).
    Enqueues transcription (B4); extraction joins it in B5."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")

    ready = {a.type for a in project.assets if a.status == AssetStatus.READY}
    missing = REQUIRED_ASSET_TYPES - ready
    if missing:
        raise HTTPException(
            409, "missing READY assets: " + ", ".join(sorted(m.value for m in missing)))
    if project.status not in (JobStatus.CREATED, JobStatus.FAILED):
        raise HTTPException(409, f"already started (status: {project.status.value})")

    project.status = JobStatus.TRANSCRIBING
    db.commit()
    # transcription and extraction run in parallel; whichever finishes second
    # triggers selection (arch §6).
    queue.enqueue(transcribe_stage, project_id)
    queue.enqueue(extract_stage, project_id)
    return {"project_id": project_id, "status": project.status.value}


@router.get("/projects/{project_id}/status", response_model=StatusOut)
def get_status(project_id: str, db: Session = Depends(get_db)):
    """Current stage & per-stage progress (FR-24)."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    has_transcript = (
        db.query(Transcript).filter_by(project_id=project_id).first() is not None)
    has_key_points = (
        db.query(KeyPoint).filter_by(project_id=project_id).first() is not None)
    has_clip_list = (
        db.query(ClipList).filter_by(project_id=project_id).first() is not None)
    return StatusOut(project_id=project_id, status=project.status.value,
                     stages=_build_stages(project.status, has_transcript,
                                          has_key_points, has_clip_list))


def _require_clip(db: Session, project_id: str):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    clip = db.query(ClipList).filter_by(project_id=project_id).one_or_none()
    if clip is None:
        raise HTTPException(404, "no clip list yet — selection has not completed")
    return project, clip


def _clip_list_out(clip: ClipList, key_points: list[KeyPoint]) -> ClipListOut:
    """Shape the response, recomputing coverage + total from the live segments."""
    segs = sorted(clip.segments, key=lambda s: s.order)
    covered = {s.key_point_id for s in segs if s.key_point_id}
    uncovered = [kp.id for kp in key_points if kp.id not in covered]
    total = int(round(sum(s.end_sec - s.start_sec for s in segs)))
    return ClipListOut(
        id=clip.id, total_duration_sec=total,
        approval_status=clip.approval_status.value,
        uncovered_key_point_ids=uncovered,
        segments=[SegmentOut(id=s.id, order=s.order, start_sec=s.start_sec,
                             end_sec=s.end_sec, transcript_snippet=s.transcript_snippet,
                             confidence=s.confidence, key_point_id=s.key_point_id,
                             locked=s.locked) for s in segs])


@router.get("/projects/{project_id}/cliplist", response_model=ClipListOut)
def get_cliplist(project_id: str, db: Session = Depends(get_db)):
    """The proposed clip list for review (FR-16)."""
    _, clip = _require_clip(db, project_id)
    key_points = db.query(KeyPoint).filter_by(project_id=project_id).all()
    return _clip_list_out(clip, key_points)


@router.patch("/projects/{project_id}/cliplist", response_model=ClipListOut)
def patch_cliplist(project_id: str, body: ClipListPatch, db: Session = Depends(get_db)):
    """Apply reorder / remove / nudge / lock edits (FR-17, FR-18). Boundary nudges
    snap to silence (FR-15); coverage + total are recomputed."""
    _, clip = _require_clip(db, project_id)
    if clip.approval_status == ApprovalStatus.APPROVED:
        raise HTTPException(409, "clip list already approved; cannot edit")

    segs = {s.id: s for s in clip.segments}
    transcript = db.query(Transcript).filter_by(project_id=project_id).one_or_none()
    silence = sorted(set(transcript.silence_points)) if transcript else []

    for edit in body.edits:
        seg = segs.get(edit.segment_id)
        if seg is None:
            raise HTTPException(404, f"segment {edit.segment_id} not found in this clip list")
        if edit.remove:
            db.delete(seg)
            segs.pop(edit.segment_id)
            continue
        if edit.order is not None:
            seg.order = edit.order
        if edit.locked is not None:
            seg.locked = edit.locked
        if edit.start_sec is not None:
            seg.start_sec = round(snap_to_silence(edit.start_sec, silence), 3)
        if edit.end_sec is not None:
            seg.end_sec = round(snap_to_silence(edit.end_sec, silence), 3)
        if seg.end_sec <= seg.start_sec:
            raise HTTPException(422, f"segment {seg.id} has non-positive duration after nudge")

    db.flush()
    # renumber order contiguously (reorder edits may leave gaps/dupes)
    for i, seg in enumerate(sorted(segs.values(), key=lambda s: (s.order, s.start_sec))):
        seg.order = i

    key_points = db.query(KeyPoint).filter_by(project_id=project_id).all()
    covered = {s.key_point_id for s in segs.values() if s.key_point_id}
    clip.uncovered_key_point_ids = [kp.id for kp in key_points if kp.id not in covered]
    clip.total_duration_sec = int(round(sum(s.end_sec - s.start_sec for s in segs.values())))
    db.commit()
    db.refresh(clip)
    return _clip_list_out(clip, key_points)


@router.post("/projects/{project_id}/reedit", status_code=202)
def reedit(project_id: str, db: Session = Depends(get_db),
           queue: Queue = Depends(get_queue)):
    """Re-run selection, preserving locked segments (FR-17, design back-fill).
    Async: re-opens the job and enqueues the re-edit; poll /status or /cliplist."""
    project, clip = _require_clip(db, project_id)
    if clip.approval_status == ApprovalStatus.APPROVED:
        raise HTTPException(409, "clip list already approved; cannot re-edit")
    project.status = JobStatus.SELECTING
    db.commit()
    queue.enqueue(reedit_stage, project_id)
    return {"project_id": project_id, "status": project.status.value}


@router.post("/projects/{project_id}/approve")
def approve(project_id: str):
    """Approve the cut and enqueue render (FR-19). The hard gate: render is
    only enqueued here."""
    raise HTTPException(501, "not implemented — task B7")


@router.get("/projects/{project_id}/output")
def get_output(project_id: str):
    """Render result: MP4, captions, metadata (FR-23)."""
    raise HTTPException(501, "not implemented — task B7")
