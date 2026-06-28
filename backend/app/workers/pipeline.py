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


def transcribe_stage(project_id: str) -> None:
    """Video → timestamped transcript with silence points (FR-07, FR-09).
    Calls the configured TranscriptionProvider. On success, persist Transcript
    and, if extraction is also done, enqueue select_segments_stage."""
    raise NotImplementedError("BUILD_PLAN.md task B4")


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
