"""API routes — indicative surface from architecture §7. Stubs raise
NotImplementedError; Claude Code fills these in per BUILD_PLAN.md."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.api import (
    ProjectCreate, ProjectOut, ClipListOut, ClipListPatch, StatusOut,
)

router = APIRouter()


@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate):
    """Create a project, return upload targets (FR-01..06)."""
    raise HTTPException(501, "not implemented — see BUILD_PLAN.md task B2")


@router.post("/projects/{project_id}/assets")
def register_asset(project_id: str):
    """Register an uploaded asset (video/deck/summary). Upload uses a
    pre-signed URL direct to object storage; this records the result."""
    raise HTTPException(501, "not implemented — task B2")


@router.post("/projects/{project_id}/start")
def start_processing(project_id: str):
    """Begin processing once all three assets present (FR-04). Enqueues
    transcription + extraction."""
    raise HTTPException(501, "not implemented — task B4")


@router.get("/projects/{project_id}/status", response_model=StatusOut)
def get_status(project_id: str):
    """Current stage & per-stage progress (FR-24)."""
    raise HTTPException(501, "not implemented — task B4")


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
