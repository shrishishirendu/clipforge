"""Pipeline worker stubs (architecture §4.4, §6). Each function is one stage,
runs in a worker process, calls the relevant provider through its interface,
writes results to the data layer, and advances the job.

Orchestration order (architecture §6):
  transcribe  ┐
              ├─→ select_segments ─→ [APPROVAL GATE] ─→ render
  extract     ┘

The approval gate is NOT a worker — render is only enqueued by the /approve
endpoint (FR-19). Each stage persists output before reporting done, so a closed
tab loses nothing (FR-25) and a failed stage retries from the last good state
(NFR-07).
"""
from __future__ import annotations

import os
import tempfile

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.entities import (
    AssetStatus, AssetType, JobStatus, MediaAsset, Project, Transcript,
)
from app.services.interfaces import ObjectStorage, TranscriptionProvider
from app.services.storage import get_storage
from app.services.transcription import get_transcription_provider


def transcribe_stage(project_id: str) -> None:
    """Video → timestamped transcript with silence points (FR-07, FR-09).
    Enqueued by POST /start; calls the configured TranscriptionProvider and
    persists the Transcript. Thin entrypoint: builds real deps and delegates to
    run_transcription (which tests drive with doubles)."""
    db = SessionLocal()
    try:
        run_transcription(db, get_storage(), get_transcription_provider(), project_id)
    finally:
        db.close()


def run_transcription(db: Session, storage: ObjectStorage,
                      provider: TranscriptionProvider, project_id: str) -> Project:
    """Download the project's video, transcribe it, and persist the Transcript.
    On failure, mark the job FAILED — completed uploads are preserved (NFR-07)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    video = next((a for a in project.assets
                  if a.type == AssetType.VIDEO and a.status == AssetStatus.READY), None)
    if video is None:
        raise ValueError(f"project {project_id} has no READY video asset")

    project.status = JobStatus.TRANSCRIBING
    db.commit()
    try:
        result = _transcribe_asset(storage, provider, project, video)
        _persist_transcript(db, project_id, result)
        # The B4 slice ends at "transcript stored". Advance past transcription;
        # B5 wires parallel extraction + converge-to-selection orchestration.
        project.status = JobStatus.EXTRACTING
        db.commit()
    except Exception:
        db.rollback()
        failed = db.get(Project, project_id)
        if failed is not None:
            failed.status = JobStatus.FAILED
            db.commit()
        raise
    return project


def _transcribe_asset(storage: ObjectStorage, provider: TranscriptionProvider,
                      project: Project, video: MediaAsset) -> dict:
    """Pull the video to a temp file and run the provider; always clean up."""
    suffix = os.path.splitext(video.storage_uri)[1] or ".mp4"
    fd, tmp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        storage.download_to_path(video.storage_uri, tmp_path)
        return provider.transcribe(tmp_path, list(project.vocabulary or []))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _persist_transcript(db: Session, project_id: str, result: dict) -> None:
    """Persist the transcript, replacing any prior one so a retry is idempotent."""
    existing = db.query(Transcript).filter_by(project_id=project_id).one_or_none()
    if existing is not None:
        db.delete(existing)
        db.flush()
    db.add(Transcript(
        project_id=project_id,
        full_text=result["full_text"],
        word_timings=result["word_timings"],
        silence_points=result["silence_points"],
    ))
    db.flush()


def extract_stage(project_id: str) -> None:
    """Deck + summary → key points (FR-10, FR-11). python-pptx / python-docx /
    pypdf. Persist KeyPoints; if transcription also done, enqueue selection."""
    raise NotImplementedError("BUILD_PLAN.md task B5")


def select_segments_stage(project_id: str) -> None:
    """Key points + transcript → ClipList (FR-12..14). Calls
    services.segment_selection.select_segments, snaps boundaries to silence
    (FR-15), persists ClipList, sets status AWAITING_REVIEW, notifies. STOPS."""
    raise NotImplementedError("BUILD_PLAN.md task B5")


def render_stage(project_id: str) -> None:
    """Approved ClipList → MP4 + captions (FR-20, FR-21, FR-23). Calls the
    MediaEngine (FFmpeg). Only ever enqueued by /approve. Persist RenderJob."""
    raise NotImplementedError("BUILD_PLAN.md task B7")
