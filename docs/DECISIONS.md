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
