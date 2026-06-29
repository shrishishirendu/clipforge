"""Pydantic request/response schemas for the API surface (architecture §7)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = "Untitled"
    target_min_sec: int = 180
    target_max_sec: int = 240
    vocabulary: list[str] = Field(default_factory=list)


class ProjectOut(BaseModel):
    id: str
    title: str
    status: str


class AssetUploadRequest(BaseModel):
    """Request a presigned upload slot for one asset (FR-01..03)."""
    type: str            # "video" | "deck" | "summary"
    filename: str        # original name; the extension determines `format`


class AssetUploadResponse(BaseModel):
    """The presigned PUT target — client uploads the file directly to storage."""
    asset_id: str
    type: str
    storage_uri: str     # object key in the media bucket
    upload_url: str      # presigned PUT URL (arch §7: bypasses the app tier)
    expires_in: int


class AssetOut(BaseModel):
    """A registered asset and its upload state."""
    id: str
    project_id: str
    type: str
    status: str          # "pending" | "ready"
    format: str
    size_bytes: int
    storage_uri: str


class SegmentOut(BaseModel):
    id: str
    order: int
    start_sec: float
    end_sec: float
    transcript_snippet: str
    confidence: float
    key_point_id: str | None
    locked: bool


class ClipListOut(BaseModel):
    id: str
    total_duration_sec: int
    approval_status: str
    uncovered_key_point_ids: list[str]
    segments: list[SegmentOut]


class SegmentEdit(BaseModel):
    """One reviewer edit (FR-17). Reorder, nudge, lock, or remove."""
    segment_id: str
    order: int | None = None
    start_sec: float | None = None
    end_sec: float | None = None
    locked: bool | None = None
    remove: bool = False


class ClipListPatch(BaseModel):
    edits: list[SegmentEdit]


class StatusOut(BaseModel):
    project_id: str
    status: str
    stages: list[dict]  # [{name, state, pct, duration_sec}]


class ApproveRequest(BaseModel):
    """Approve the cut (FR-19). confirm_gaps acknowledges uncovered key points
    (approve-with-gaps confirmation, design back-fill)."""
    confirm_gaps: bool = False


class OutputOut(BaseModel):
    """Render result with time-limited download links (FR-23)."""
    project_id: str
    status: str               # render job status, e.g. "complete"
    resolution: str
    size_bytes: int
    video_url: str | None      # presigned GET for the MP4
    captions_url: str | None   # presigned GET for the sidecar SRT
