# Decisions log

Design/architecture decisions made outside the locked requirements (v0.1),
pending back-fill into requirements v0.2:
- Segment locking; "re-edit cut" preserves locked segments (extends FR-17)
- Key-point coverage tracking + gaps panel (new FR)
- Approve-with-gaps confirmation before render (extends FR-19)
- Undo on segment removal (extends FR-17)
- Boundary nudges ±0.5s snapped to silence (clarifies FR-15)
- Stage failure with retry, preserving completed work (clarifies NFR-07)
- Output resolution choice + SRT caption download (extends FR-21, FR-23)

## B2 — Asset upload via presigned URLs (FR-01..06)
- Two-phase upload: `POST /projects/{id}/assets` validates type/extension and
  returns a presigned S3/MinIO **PUT** URL, recording the asset as `pending`; the
  client uploads directly to storage (arch §7, keeps large video off the app tier);
  `POST /projects/{id}/assets/{asset_id}/complete` (asset-complete callback)
  confirms the object via head_object, records the real size, and marks it `ready`.
- Adds a `status` enum column (`pending`/`ready`) to MediaAsset — not in the §5
  data model; lets B4's `/start` check "all three assets present" and makes uploads
  resumable. Flag for back-fill into requirements v0.2.
- The `/complete` callback endpoint is not in the §7 indicative API surface; add it.
- Size limits enforced at the callback against the true object size (FR-04):
  video 2 GiB, deck 100 MiB, summary 25 MiB (indicative; tune later).
- Auth is deferred to Phase 5 (NFR-05); until then projects use a single
  placeholder owner (`demo-user`).

## B4 — Transcription slice (FR-07, FR-09, FR-24, FR-25)
- Local transcription via **faster-whisper** (default `whisper_local`), behind the
  TranscriptionProvider interface; Deepgram/AssemblyAI remain swappable (OQ-02).
  faster-whisper decodes the video via PyAV, so **no system FFmpeg is needed for
  transcription** (FFmpeg is still required for B7 render).
- **Silence points (FR-09/FR-15)** are derived as: clip start, clip end, and the
  midpoint of every inter-word gap >= `silence_gap_sec` (default 0.4s). These feed
  server-side boundary snapping later.
- Custom vocabulary is passed as the Whisper `initial_prompt` to bias names/jargon
  (FR-08).
- **`POST /start`** requires one READY asset of each type (video/deck/summary, FR-04)
  and is idempotent (only allowed from CREATED/FAILED). In B4 it enqueues only
  transcription; B5 adds parallel extraction.
- **Status convention (placeholder):** after the transcript is stored, the job is
  set to `EXTRACTING` to mean "past transcription". B5 replaces this with real
  parallel transcribe+extract orchestration converging to `SELECTING`.
- On stage failure the job is set to `FAILED` and completed uploads/transcript are
  preserved; re-running replaces the transcript (idempotent retry, NFR-07).
- Env note: on Windows+Anaconda a global `sitecustomize.py` patches `shutil.move`
  into a 2-arg form that breaks huggingface_hub model downloads. `app/core/winshim.py`
  re-wraps it (no-op on stock/Linux shutil) so faster-whisper can cache models.

## B5 — Extraction + segment selection (core IP) (FR-10..15, FR-19)
- The raw model call is behind `LLMProvider` (Claude Sonnet, NFR-02); the prompt,
  strict-JSON validation, and snapping stay in `services/segment_selection.py` (the IP).
- Internal contract uses numeric `start_sec`/`end_sec` (matching Segment + transcript),
  not the `HH:MM:SS` shown illustratively in arch §9.
- Transcript is sent to the LLM as compact **lines** (word timings grouped at silence
  boundaries) + the silence-point list, not raw word timings (token cost).
- **Snap-to-silence (FR-15)** is enforced server-side: each boundary snaps to the
  nearest silence point; a segment that collapses to zero length is dropped.
- Over-target is **flagged** (`_over_target`), never silently truncated (FR-14).
- Key points: deck → one per slide/page; summary → one per line/paragraph (bullet
  markers stripped). Behind the `DocumentParser` interface (python-pptx/docx/pypdf).
- **Parallel-then-converge:** `/start` enqueues transcribe + extract; whichever lands
  second calls `maybe_enqueue_selection`, which fires selection exactly once (guarded
  on status ∈ {transcribing, extracting}). NOTE: single-worker safe; the converge has
  a theoretical double-enqueue race under concurrent workers — harden in Phase 5.
- Selection persists the ClipList + ordered Segments and sets `AWAITING_REVIEW` — the
  hard approval gate; render is never enqueued here (FR-19).
- Status: `/start` sets the headline to `TRANSCRIBING` for the whole parallel phase;
  `/status` derives per-stage states (transcription/extraction/selection/review/render)
  from persisted artifacts (FR-24).

## B6 — Clip-list review API (FR-16, FR-17, FR-18)
- **Coverage is recomputed from the live segments** on every read/edit (covered =
  key_point_ids referenced by segments; uncovered = the rest). The LLM's
  uncovered list is not trusted as durable state — avoids drift as the user edits.
- `PATCH /cliplist` applies a batch of edits: remove, reorder (`order`, then
  contiguously renumbered), lock/unlock, and boundary nudge. **Nudged boundaries
  snap to the nearest silence point (FR-15)**; an edit that collapses a segment
  (end ≤ start) is rejected 422. Edits are blocked once the list is APPROVED (409).
- `POST /reedit` is **async** (matches the job model): it re-opens the job
  (status → SELECTING) and enqueues `reedit_stage`; the client polls /status or
  re-fetches /cliplist. `run_reedit` keeps locked segments exactly and asks the LLM
  to re-select only the key points not covered by locked segments, within the
  remaining time budget; new segments overlapping a locked range are dropped.
- `rebuild_clip_list` is the single writer for clip lists (selection, re-edit),
  recomputing coverage/total and preserving each segment's `locked` flag.

## B7 — Approval gate, render, output (FR-19, FR-20, FR-21, FR-23, NFR-07)
- **The gate (FR-19):** `POST /approve` is the ONLY place `render_stage` is enqueued.
  It requires status AWAITING_REVIEW + ≥1 segment, and `run_render` independently
  refuses to run unless the clip list is APPROVED (defence in depth).
- **Approve-with-gaps:** if any key point is uncovered, `/approve` returns 409 with
  the uncovered ids; the client re-POSTs `{confirm_gaps: true}` to proceed.
- **Render:** FFmpeg behind `MediaEngine` (single `filter_complex` pass: trim each
  segment, scale to the target height, concat). Re-encode (not stream-copy) so cuts
  land exactly on the silence-snapped boundaries, not keyframes (FR-20). The engine
  works on local files; `run_render` handles MinIO download/upload.
- **Captions:** sidecar `.srt` (OQ-03), built in Python from the segments on the
  *output* timeline (`services/captions.build_srt`); reviewable/correctable (NFR-03).
- **Output:** `GET /output` returns presigned GET links for the MP4 + SRT plus
  metadata (resolution, size). Default resolution 1080p (`settings.output_resolution`).
- Env: FFmpeg is required for render (installed via winget; `settings.ffmpeg_bin`
  defaults to PATH, override with `FFMPEG_BIN` on dev boxes where it isn't on PATH).
