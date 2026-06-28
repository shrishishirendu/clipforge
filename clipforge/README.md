# ClipForge — AI Video Summarisation & Auto-Editing Platform

Takes a long talk (video + slide deck + summary document) and produces a tight
3–4 minute edited cut, with a human reviewing and approving the cut before it renders.

## Status
Scaffold v0.1 — generated from the locked Requirements, Design, and Technical
Architecture documents (see `/docs`). Not yet functional; this is the skeleton
for iterative development in Claude Code.

## Architecture in one paragraph
Asynchronous, job-based pipeline. A job moves through transcription → content
extraction (parallel) → segment selection (Claude) → **human approval gate (hard
pause)** → render. Transcription, the LLM, and FFmpeg sit behind interfaces so
they can be swapped. State is persisted at every stage boundary so work survives
a closed tab or a failed stage. See `docs/technical-architecture` and `BUILD_PLAN.md`.

## Layout
- `backend/`  — FastAPI app, data models, API, workers, services
- `frontend/` — React/Next.js (upload, status, clip review, output screens)
- `docs/`     — requirements, design notes, architecture (drop the .docx/.png here)
- `infra/`    — docker-compose for local dev
- `BUILD_PLAN.md` — ordered task breakdown for Claude Code

## Quick start (once implemented)
    cd infra && docker compose up        # postgres, redis, minio
    cd backend && uvicorn app.main:app --reload
    cd frontend && npm run dev

## The single most important file
`backend/app/services/segment_selection.py` — the core IP. Maps key points to
transcript segments via Claude and returns a validated clip list. Read the
contract in the technical architecture (section 9) before touching it.
