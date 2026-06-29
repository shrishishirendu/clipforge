"""Pipeline worker stages (architecture §4.4, §6). Each stage runs in a worker,
calls a provider through its interface, writes results to the data layer, and
advances the job.

Orchestration (architecture §6):
  transcribe  ┐
              ├─→ select_segments ─→ [APPROVAL GATE] ─→ render
  extract     ┘

Transcription and extraction run in parallel; whichever finishes second triggers
selection (maybe_enqueue_selection). The approval gate is NOT a worker — render is
only enqueued by the /approve endpoint (FR-19). Each stage persists output before
reporting done, so a closed tab loses nothing (FR-25) and a failed stage retries
from the last good state (NFR-07).

Thin *_stage entrypoints build real deps and delegate to run_* cores that tests
drive with doubles.
"""
from __future__ import annotations

import os
import tempfile

from rq import Queue
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.entities import (
    ApprovalStatus, AssetStatus, AssetType, ClipList, JobStatus, KeyPoint,
    MediaAsset, Project, Segment, Transcript,
)
from app.services.extraction import get_document_parser
from app.services.interfaces import (
    DocumentParser, LLMProvider, ObjectStorage, TranscriptionProvider,
)
from app.services.llm import get_llm_provider
from app.services.segment_selection import select_segments
from app.services.storage import get_storage
from app.services.transcription import get_transcription_provider
from app.workers.queue import get_queue

# Selection is enqueued once, only while the job is still in its parallel phase.
_SELECTION_ELIGIBLE = (JobStatus.TRANSCRIBING, JobStatus.EXTRACTING)


# === Transcription (FR-07, FR-09) ===========================================

def transcribe_stage(project_id: str) -> None:
    db = SessionLocal()
    try:
        run_transcription(db, get_storage(), get_transcription_provider(), project_id)
        maybe_enqueue_selection(db, get_queue(), project_id)
    finally:
        db.close()


def run_transcription(db: Session, storage: ObjectStorage,
                      provider: TranscriptionProvider, project_id: str) -> Project:
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
        suffix = os.path.splitext(video.storage_uri)[1] or ".mp4"
        result = _with_downloaded(storage, video.storage_uri, suffix,
                                  lambda p: provider.transcribe(p, list(project.vocabulary or [])))
        _persist_transcript(db, project_id, result)
        db.commit()
    except Exception:
        _mark_failed(db, project_id)
        raise
    return project


def _persist_transcript(db: Session, project_id: str, result: dict) -> None:
    existing = db.query(Transcript).filter_by(project_id=project_id).one_or_none()
    if existing is not None:
        db.delete(existing)
        db.flush()
    db.add(Transcript(project_id=project_id, full_text=result["full_text"],
                      word_timings=result["word_timings"],
                      silence_points=result["silence_points"]))
    db.flush()


# === Extraction (FR-10, FR-11) ==============================================

def extract_stage(project_id: str) -> None:
    db = SessionLocal()
    try:
        run_extraction(db, get_storage(), get_document_parser(), project_id)
        maybe_enqueue_selection(db, get_queue(), project_id)
    finally:
        db.close()


def run_extraction(db: Session, storage: ObjectStorage,
                   parser: DocumentParser, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    docs = [a for a in project.assets
            if a.type in (AssetType.DECK, AssetType.SUMMARY)
            and a.status == AssetStatus.READY]
    if not docs:
        raise ValueError(f"project {project_id} has no READY deck/summary assets")

    try:
        points: list[dict] = []
        for asset in docs:
            suffix = "." + asset.format if asset.format else os.path.splitext(asset.storage_uri)[1]
            points += _with_downloaded(
                storage, asset.storage_uri, suffix,
                lambda p, a=asset: parser.extract_key_points(p, a.type.value, a.format))
        _persist_key_points(db, project_id, points)
        db.commit()
    except Exception:
        _mark_failed(db, project_id)
        raise
    return project


def _persist_key_points(db: Session, project_id: str, points: list[dict]) -> None:
    db.query(KeyPoint).filter_by(project_id=project_id).delete()
    db.flush()
    for p in points:
        db.add(KeyPoint(project_id=project_id, text=p["text"], source=p.get("source", "")))
    db.flush()


# === Convergence ============================================================

def maybe_enqueue_selection(db: Session, queue: Queue, project_id: str) -> bool:
    """Enqueue selection once transcription AND extraction have both landed.
    Idempotent: only fires while the job is still in its parallel phase."""
    project = db.get(Project, project_id)
    if project is None or project.status not in _SELECTION_ELIGIBLE:
        return False
    has_transcript = db.query(Transcript).filter_by(project_id=project_id).first() is not None
    has_key_points = db.query(KeyPoint).filter_by(project_id=project_id).first() is not None
    if not (has_transcript and has_key_points):
        return False
    project.status = JobStatus.SELECTING
    db.commit()
    queue.enqueue(select_segments_stage, project_id)
    return True


# === Segment selection — the core IP (FR-12..15) ============================

def select_segments_stage(project_id: str) -> None:
    db = SessionLocal()
    try:
        run_selection(db, get_llm_provider(), project_id)
    finally:
        db.close()


def run_selection(db: Session, llm: LLMProvider, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    transcript = db.query(Transcript).filter_by(project_id=project_id).one_or_none()
    key_points = db.query(KeyPoint).filter_by(project_id=project_id).all()
    if transcript is None or not key_points:
        raise ValueError("selection requires a transcript and key points")

    project.status = JobStatus.SELECTING
    db.commit()
    try:
        result = select_segments(
            [{"id": kp.id, "text": kp.text, "source": kp.source} for kp in key_points],
            {"word_timings": transcript.word_timings,
             "silence_points": transcript.silence_points,
             "full_text": transcript.full_text},
            project.target_min_sec, project.target_max_sec, llm=llm)
        _persist_clip_list(db, project_id, result)
        project.status = JobStatus.AWAITING_REVIEW  # the approval gate (FR-19)
        db.commit()
    except Exception:
        _mark_failed(db, project_id)
        raise
    return project


def _persist_clip_list(db: Session, project_id: str, result: dict) -> None:
    existing = db.query(ClipList).filter_by(project_id=project_id).one_or_none()
    if existing is not None:
        db.delete(existing)  # cascades to segments
        db.flush()
    clip = ClipList(project_id=project_id,
                    total_duration_sec=int(round(result.get("total_duration_sec", 0))),
                    approval_status=ApprovalStatus.PENDING,
                    uncovered_key_point_ids=result.get("uncovered_key_point_ids", []))
    db.add(clip)
    db.flush()
    for i, seg in enumerate(result["segments"]):
        db.add(Segment(clip_list_id=clip.id, order=i,
                       start_sec=float(seg["start_sec"]), end_sec=float(seg["end_sec"]),
                       transcript_snippet=seg.get("transcript", ""),
                       confidence=float(seg.get("confidence", 0.0)),
                       key_point_id=seg.get("key_point_id"), locked=False))
    db.flush()


# === Render (B7) ============================================================

def render_stage(project_id: str) -> None:
    """Approved ClipList → MP4 + captions (FR-20, FR-21, FR-23). Calls the
    MediaEngine (FFmpeg). Only ever enqueued by /approve. Persist RenderJob."""
    raise NotImplementedError("BUILD_PLAN.md task B7")


# === Shared helpers =========================================================

def _with_downloaded(storage: ObjectStorage, key: str, suffix: str, fn):
    """Download `key` to a temp file, run fn(path), always clean up."""
    fd, tmp_path = tempfile.mkstemp(suffix=suffix or "")
    os.close(fd)
    try:
        storage.download_to_path(key, tmp_path)
        return fn(tmp_path)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _mark_failed(db: Session, project_id: str) -> None:
    """Roll back partial work and flag the job FAILED, preserving prior stages (NFR-07)."""
    db.rollback()
    project = db.get(Project, project_id)
    if project is not None:
        project.status = JobStatus.FAILED
        db.commit()
