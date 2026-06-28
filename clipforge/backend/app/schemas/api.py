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
