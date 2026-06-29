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

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.entities import (
    ApprovalStatus, AssetStatus, AssetType, ClipList, JobStatus, KeyPoint,
    MediaAsset, Project, RenderJob, Segment, Transcript,
)
from app.services.captions import build_srt
from app.services.extraction import get_document_parser
from app.services.interfaces import (
    DocumentParser, LLMProvider, MediaEngine, ObjectStorage, TranscriptionProvider,
)
from app.services.llm import get_llm_provider
from app.services.media import get_media_engine
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
        rebuild_clip_list(db, project_id, result["segments"], key_points)
        project.status = JobStatus.AWAITING_REVIEW  # the approval gate (FR-19)
        db.commit()
    except Exception:
        _mark_failed(db, project_id)
        raise
    return project


def rebuild_clip_list(db: Session, project_id: str, segments: list[dict],
                      key_points: list) -> ClipList:
    """Replace the clip list with `segments`, recomputing total + coverage from the
    segments themselves (coverage = key points referenced; uncovered = the rest).
    Preserves each segment's `locked` flag. Used by selection, re-edit, and PATCH."""
    existing = db.query(ClipList).filter_by(project_id=project_id).one_or_none()
    if existing is not None:
        db.delete(existing)  # cascades to segments
        db.flush()
    covered = {s.get("key_point_id") for s in segments if s.get("key_point_id")}
    uncovered = [kp.id for kp in key_points if kp.id not in covered]
    total = sum(s["end_sec"] - s["start_sec"] for s in segments)
    clip = ClipList(project_id=project_id, total_duration_sec=int(round(total)),
                    approval_status=ApprovalStatus.PENDING,
                    uncovered_key_point_ids=uncovered)
    db.add(clip)
    db.flush()
    for i, s in enumerate(segments):
        db.add(Segment(
            clip_list_id=clip.id, order=i,
            start_sec=float(s["start_sec"]), end_sec=float(s["end_sec"]),
            transcript_snippet=s.get("transcript", s.get("transcript_snippet", "")),
            confidence=float(s.get("confidence", 0.0)),
            key_point_id=s.get("key_point_id"), locked=bool(s.get("locked", False))))
    db.flush()
    return clip


# === Re-edit, preserving locked segments (FR-17, design back-fill) ==========

def reedit_stage(project_id: str) -> None:
    db = SessionLocal()
    try:
        run_reedit(db, get_llm_provider(), project_id)
    finally:
        db.close()


def _overlaps_any(start: float, end: float, locked: list) -> bool:
    return any(not (end <= L.start_sec or start >= L.end_sec) for L in locked)


def run_reedit(db: Session, llm: LLMProvider, project_id: str) -> Project:
    """Re-run selection while keeping locked segments exactly. The LLM only
    re-selects the key points not already covered by locked segments, within the
    remaining time budget; new segments overlapping a locked range are dropped."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    clip = db.query(ClipList).filter_by(project_id=project_id).one_or_none()
    transcript = db.query(Transcript).filter_by(project_id=project_id).one_or_none()
    key_points = db.query(KeyPoint).filter_by(project_id=project_id).all()
    if clip is None or transcript is None or not key_points:
        raise ValueError("re-edit requires an existing clip list, transcript, key points")

    locked = [s for s in clip.segments if s.locked]
    project.status = JobStatus.SELECTING
    db.commit()
    try:
        locked_kp_ids = {s.key_point_id for s in locked if s.key_point_id}
        locked_duration = sum(s.end_sec - s.start_sec for s in locked)
        remaining_kps = [kp for kp in key_points if kp.id not in locked_kp_ids]
        budget_max = max(0, project.target_max_sec - int(round(locked_duration)))

        proposal = []
        if remaining_kps and budget_max > 0:
            result = select_segments(
                [{"id": kp.id, "text": kp.text, "source": kp.source} for kp in remaining_kps],
                {"word_timings": transcript.word_timings,
                 "silence_points": transcript.silence_points,
                 "full_text": transcript.full_text},
                min(project.target_min_sec, budget_max), budget_max, llm=llm)
            proposal = [s for s in result["segments"]
                        if not _overlaps_any(s["start_sec"], s["end_sec"], locked)]

        merged = [{"start_sec": s.start_sec, "end_sec": s.end_sec,
                   "transcript": s.transcript_snippet, "key_point_id": s.key_point_id,
                   "confidence": s.confidence, "locked": True} for s in locked]
        merged += [{**s, "locked": False} for s in proposal]
        merged.sort(key=lambda x: x["start_sec"])

        rebuild_clip_list(db, project_id, merged, key_points)
        project.status = JobStatus.AWAITING_REVIEW  # re-opened for review (FR-19)
        db.commit()
    except Exception:
        _mark_failed(db, project_id)
        raise
    return project


# === Render (B7) ============================================================

def render_stage(project_id: str) -> None:
    db = SessionLocal()
    try:
        run_render(db, get_storage(), get_media_engine(), project_id)
    finally:
        db.close()


def run_render(db: Session, storage: ObjectStorage, engine: MediaEngine,
               project_id: str) -> RenderJob:
    """Approved ClipList → MP4 + sidecar SRT (FR-20, FR-21, FR-23). Safety net: it
    refuses to run unless the clip list is APPROVED — render is only reachable via
    /approve (FR-19)."""
    project = db.get(Project, project_id)
    if project is None:
        raise ValueError(f"project {project_id} not found")
    clip = db.query(ClipList).filter_by(project_id=project_id).one_or_none()
    if clip is None or clip.approval_status != ApprovalStatus.APPROVED:
        raise ValueError("render requires an APPROVED clip list (the gate, FR-19)")
    segments = sorted(clip.segments, key=lambda s: s.order)
    if not segments:
        raise ValueError("approved clip list has no segments to render")
    video = next((a for a in project.assets
                  if a.type == AssetType.VIDEO and a.status == AssetStatus.READY), None)
    if video is None:
        raise ValueError("no READY source video to render from")

    project.status = JobStatus.RENDERING
    db.commit()
    seg_dicts = [{"start_sec": s.start_sec, "end_sec": s.end_sec,
                  "transcript": s.transcript_snippet} for s in segments]
    tmp_dir = tempfile.mkdtemp(prefix="clipforge-render-")
    src_path = os.path.join(tmp_dir, "source" + (os.path.splitext(video.storage_uri)[1] or ".mp4"))
    out_mp4 = os.path.join(tmp_dir, "cut.mp4")
    out_srt = os.path.join(tmp_dir, "cut.srt")
    try:
        storage.download_to_path(video.storage_uri, src_path)
        info = engine.render(src_path, seg_dicts, out_mp4, resolution=settings.output_resolution)
        with open(out_srt, "w", encoding="utf-8") as fh:
            fh.write(build_srt(seg_dicts))

        mp4_key = f"projects/{project_id}/output/cut.mp4"
        srt_key = f"projects/{project_id}/output/cut.srt"
        storage.upload_file(out_mp4, mp4_key, "video/mp4")
        storage.upload_file(out_srt, srt_key, "application/x-subrip")

        render_job = _persist_render_job(db, project_id, mp4_key, srt_key,
                                         info["size_bytes"], settings.output_resolution)
        project.status = JobStatus.COMPLETE
        db.commit()
        return render_job
    except Exception:
        _mark_failed(db, project_id)
        raise
    finally:
        for p in (src_path, out_mp4, out_srt):
            try:
                os.remove(p)
            except OSError:
                pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def _persist_render_job(db: Session, project_id: str, output_key: str,
                        caption_key: str, size_bytes: int, resolution: str) -> RenderJob:
    existing = db.query(RenderJob).filter_by(project_id=project_id).one_or_none()
    if existing is not None:
        db.delete(existing)
        db.flush()
    job = RenderJob(project_id=project_id, status="complete", output_uri=output_key,
                    caption_uri=caption_key, resolution=resolution, size_bytes=size_bytes)
    db.add(job)
    db.flush()
    return job


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
