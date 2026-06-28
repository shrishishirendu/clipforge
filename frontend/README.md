# ClipForge frontend

React/Next.js. Four screens, designed in Claude Design (see docs/design):
1. Upload — three dropzones, target-length, vocabulary (FR-01..06)
2. Processing/status — pipeline stepper + per-stage status (FR-24)
3. Clip review & approval — segment cards, key-point coverage panel,
   boundary nudges, lock, approve-with-gaps confirmation (FR-16..19) ← the core screen
4. Output/download — player, Download MP4, SRT, copy link (FR-20, FR-23)

Build order in BUILD_PLAN.md (tasks F1–F4). Build screen 3 first — it's the
highest-value and most complex.
