# ClipForge — Build Plan

Ordered tasks for Claude Code. The principle: get one thread working through the
whole stack first (Phase 1), then widen. Each task is one commit. Keep pytest green.

## Phase 0 — Foundations
- **B0** Stand up infra: `cd infra && docker compose up`. Confirm Postgres,
  Redis, MinIO reachable. Create the S3 bucket.
- **B1** Wire SQLAlchemy to Postgres, add Alembic, generate the initial migration
  from app/models. Confirm the seven tables are created.

## Phase 1 — One vertical slice (upload → transcribe → store)
The goal: prove the async pipeline end-to-end on the simplest path before
building the hard stages.
- **B2** Implement POST /projects, POST /projects/{id}/assets (pre-signed S3
  upload URLs), and the asset-complete callback. Test: create a project, upload
  three files, see three MediaAssets. (FR-01..06)
- **B3** Add the RQ queue + a worker entrypoint. Prove a trivial job runs.
- **B4** Implement `transcribe_stage` behind TranscriptionProvider (start with
  local Whisper). POST /start enqueues it; GET /status reports progress. Persist
  Transcript with word timings + silence points. Test the slice end-to-end.
  (FR-07, FR-09, FR-24, FR-25)

## Phase 2 — The intelligence
- **B5** Implement `extract_stage` (python-pptx/docx/pypdf → KeyPoints) and
  `select_segments_stage`. Wire the parallel-then-converge orchestration. Snap
  segment boundaries to silence (FR-15). Set status AWAITING_REVIEW. (FR-10..15)
- **B6** Implement GET/PATCH /cliplist and POST /reedit: serve the proposed clip
  list, apply reorder/remove/nudge/lock edits, recompute coverage + total,
  re-edit preserving locked segments. (FR-16, FR-17, coverage back-fill)

## Phase 3 — Close the loop
- **B7** Implement POST /approve (the gate → enqueue render), `render_stage`
  behind MediaEngine (FFmpeg: cut, concat, captions), and GET /output. Enforce:
  render never runs without approval. Add approve-with-gaps confirmation support.
  (FR-19, FR-20, FR-21, FR-23, NFR-07)

## Phase 4 — Frontend
- **F1** Upload screen (three dropzones, target-length, vocabulary). (FR-01..06)
- **F2** Processing/status screen (stepper + per-stage status + failure/retry).
- **F3** Clip review & approval screen — THE core screen. Segment cards,
  key-point coverage panel, boundary nudges, lock, drag-reorder, undo on remove,
  approve-with-gaps confirmation. Build this most carefully. (FR-16..19)
- **F4** Output/download screen (player, Download MP4, SRT, copy link, re-edit).

## Phase 5 — Hardening
- Per-stage retry + idempotency (NFR-07). Auth at the gateway (NFR-05).
- Cost/latency check on a real 60-min video (NFR-01, NFR-02).
- Custom vocabulary applied to transcription (FR-08).

## Definition of done for the MVP
A user uploads video+deck+summary, the system proposes a cut, the user reviews
and approves it, and downloads a 3–4 min MP4 with captions — with ~5 min of human
review and no video editing. (Acceptance criteria, requirements §8.)
