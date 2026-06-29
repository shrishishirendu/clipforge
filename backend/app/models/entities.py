"""The seven core entities. Project is the aggregate root.

Maps directly to the data model in the technical architecture (§5) and the
ER diagram. Fields flagged (design back-fill) came from the Claude Design pass
and are pending addition to Requirements v0.2.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Float, Boolean, ForeignKey, Enum, JSON, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class JobStatus(str, enum.Enum):
    CREATED = "created"
    TRANSCRIBING = "transcribing"
    EXTRACTING = "extracting"
    SELECTING = "selecting"
    AWAITING_REVIEW = "awaiting_review"   # the approval gate (FR-19)
    RENDERING = "rendering"
    COMPLETE = "complete"
    FAILED = "failed"


class AssetType(str, enum.Enum):
    VIDEO = "video"
    DECK = "deck"
    SUMMARY = "summary"


class AssetStatus(str, enum.Enum):
    PENDING = "pending"   # presigned URL issued, awaiting client upload (B2)
    READY = "ready"       # upload confirmed via head_object (asset-complete callback)


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String, default="Untitled")
    owner_id: Mapped[str] = mapped_column(String, index=True)
    target_min_sec: Mapped[int] = mapped_column(Integer, default=180)
    target_max_sec: Mapped[int] = mapped_column(Integer, default=240)
    vocabulary: Mapped[list | None] = mapped_column(JSON, default=list)  # FR-06
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.CREATED)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    assets: Mapped[list[MediaAsset]] = relationship(back_populates="project", cascade="all, delete-orphan")
    transcript: Mapped[Transcript | None] = relationship(back_populates="project", uselist=False)
    key_points: Mapped[list[KeyPoint]] = relationship(back_populates="project", cascade="all, delete-orphan")
    clip_list: Mapped[ClipList | None] = relationship(back_populates="project", uselist=False)
    render_job: Mapped[RenderJob | None] = relationship(back_populates="project", uselist=False)


class MediaAsset(Base):
    __tablename__ = "media_assets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    type: Mapped[AssetType] = mapped_column(Enum(AssetType))
    storage_uri: Mapped[str] = mapped_column(String)  # object key in the media bucket
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str] = mapped_column(String, default="")  # file extension, e.g. "mp4"
    status: Mapped[AssetStatus] = mapped_column(Enum(AssetStatus), default=AssetStatus.PENDING)
    project: Mapped[Project] = relationship(back_populates="assets")


class Transcript(Base):
    __tablename__ = "transcripts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    word_timings: Mapped[list] = mapped_column(JSON, default=list)     # [{word, start, end}]
    silence_points: Mapped[list] = mapped_column(JSON, default=list)   # [sec, ...] for snapping (FR-15)
    full_text: Mapped[str] = mapped_column(String, default="")
    project: Mapped[Project] = relationship(back_populates="transcript")


class KeyPoint(Base):
    __tablename__ = "key_points"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    text: Mapped[str] = mapped_column(String)
    source: Mapped[str] = mapped_column(String, default="")  # e.g. "Slide 3" or "Summary"
    project: Mapped[Project] = relationship(back_populates="key_points")


class ClipList(Base):
    __tablename__ = "clip_lists"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    total_duration_sec: Mapped[int] = mapped_column(Integer, default=0)
    approval_status: Mapped[ApprovalStatus] = mapped_column(Enum(ApprovalStatus), default=ApprovalStatus.PENDING)
    uncovered_key_point_ids: Mapped[list] = mapped_column(JSON, default=list)  # coverage panel (design back-fill)
    project: Mapped[Project] = relationship(back_populates="clip_list")
    segments: Mapped[list[Segment]] = relationship(back_populates="clip_list",
                                                   cascade="all, delete-orphan",
                                                   order_by="Segment.order")


class Segment(Base):
    __tablename__ = "segments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    clip_list_id: Mapped[str] = mapped_column(ForeignKey("clip_lists.id"))
    order: Mapped[int] = mapped_column(Integer, default=0)
    start_sec: Mapped[float] = mapped_column(Float)
    end_sec: Mapped[float] = mapped_column(Float)
    transcript_snippet: Mapped[str] = mapped_column(String, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    key_point_id: Mapped[str | None] = mapped_column(String, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)  # survives re-edit (design back-fill)
    clip_list: Mapped[ClipList] = relationship(back_populates="segments")


class RenderJob(Base):
    __tablename__ = "render_jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    status: Mapped[str] = mapped_column(String, default="queued")
    output_uri: Mapped[str] = mapped_column(String, default="")
    caption_uri: Mapped[str] = mapped_column(String, default="")
    resolution: Mapped[str] = mapped_column(String, default="1080p")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    project: Mapped[Project] = relationship(back_populates="render_job")
