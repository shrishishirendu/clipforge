"""API routes — indicative surface from architecture §7. Stubs raise
NotImplementedError; Claude Code fills these in per BUILD_PLAN.md."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from rq import Queue
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import (
    AssetStatus, AssetType, ClipList, JobStatus, KeyPoint, MediaAsset, Project,
    Transcript,
)
from app.schemas.api import (
    AssetOut, AssetUploadRequest, AssetUploadResponse,
    ProjectCreate, ProjectOut, ClipListOut, ClipListPatch, StatusOut,
)
from app.services.interfaces import ObjectStorage
from app.services.storage import get_storage
from app.workers.pipeline import extract_stage, transcribe_stage
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


@router.get("/projects/{project_id}/cliplist", response_model=ClipListOut)
def get_cliplist(project_id: str):
    """The proposed clip list for review (FR-16)."""
    raise HTTPException(501, "not implemented — task B6")


@router.patch("/projects/{project_id}/cliplist", response_model=ClipListOut)
def patch_cliplist(project_id: str, body: ClipListPatch):
    """Apply reorder / remove / nudge / lock edits (FR-17). Recomputes
    coverage and total duration."""
    raise HTTPException(501, "not implemented — task B6")


@router.post("/projects/{project_id}/reedit")
def reedit(project_id: str):
    """Re-run selection, preserving locked segments (design back-fill)."""
    raise HTTPException(501, "not implemented — task B6")


@router.post("/projects/{project_id}/approve")
def approve(project_id: str):
    """Approve the cut and enqueue render (FR-19). The hard gate: render is
    only enqueued here."""
    raise HTTPException(501, "not implemented — task B7")


@router.get("/projects/{project_id}/output")
def get_output(project_id: str):
    """Render result: MP4, captions, metadata (FR-23)."""
    raise HTTPException(501, "not implemented — task B7")
