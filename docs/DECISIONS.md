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
