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
