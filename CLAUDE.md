# ClipForge — context for Claude Code

You are building ClipForge, an AI video summarisation platform. Read this file,
then BUILD_PLAN.md, then the docs in /docs before writing code.

## What it does
Takes a long talk (video + slide deck + summary document) and produces a tight
3–4 minute edited cut. A human reviews and approves the proposed cut before it
renders. This human-in-the-loop approval is the product's core value — never
auto-render without it.

## Source of truth
- docs/requirements — what to build and why (FR-xx, NFR-xx IDs)
- docs/technical-architecture — how it's structured (referenced throughout code)
- docs/design — the four screens, designed and locked
Code comments reference these IDs. Keep them accurate. If you make a design
decision not yet in the docs, note it in docs/DECISIONS.md.

## Architecture rules (do not violate)
1. Async, job-based. Long-running work (transcription, render) runs in workers
   off a queue, never inline in a request.
2. The approval gate is a HARD STOP. `render_stage` is only ever enqueued by the
   POST /approve endpoint. Selection ends by setting status AWAITING_REVIEW.
3. Persist at every stage boundary. A closed tab or failed stage must not lose
   completed work. Each stage writes output to the DB before reporting done.
4. Providers behind interfaces. Transcription, the LLM, and FFmpeg are accessed
   through app/services/interfaces.py. Don't hardcode a provider in pipeline code.
5. Use Claude Sonnet for segment selection (claude-sonnet-4-6). Not Opus — cost.

## The core IP
app/services/segment_selection.py maps key points to transcript segments and
returns a validated clip list. Read technical-architecture §9 (the contract:
strict JSON in/out, validation, snap-to-silence) before changing it.

## Tech stack
Backend: FastAPI, SQLAlchemy 2.0, Postgres, Redis + RQ (queue), boto3 (S3/MinIO),
anthropic SDK, python-pptx/python-docx/pypdf, FFmpeg.
Frontend: React/Next.js. Four screens (see frontend/README.md).

## Working agreement
- Build one vertical slice end-to-end before going wide (see BUILD_PLAN phase 1).
- Write a test for each endpoint/stage as you implement it. Keep `pytest` green.
- Small commits, one task per commit, referencing the BUILD_PLAN task id.
