# Technical Architecture — AI Video Summarisation Platform

_AI Video Summarisation & Auto-Editing Platform_

*Companion to the Requirements Specification v0.1*

| **Field**      | **Value**                                 |
|----------------|-------------------------------------------|
| Document owner | Head of Data & AI, iSOFT                  |
| Status         | DRAFT — for technical review              |
| Version        | 0.1                                       |
| Date           | 28 June 2026                              |
| Optimised for  | Repeatable product (multi-user, scalable) |
| Build profile  | Tier B — human-in-the-loop approval       |

Contents

## 1. Introduction

### 1.1 Purpose

This document describes the technical architecture for the AI Video
Summarisation & Auto-Editing Platform. It is the engineering companion
to the Requirements Specification (v0.1) and references its requirement
IDs (FR-xx, NFR-xx) throughout so the two remain coordinated. Where this
document records a design decision not yet in the requirements, it is
flagged for back-fill.

### 1.2 Architectural drivers

The shape of this architecture is dictated by four characteristics of
the problem:

- **Long-running work.** Transcription and rendering take minutes, not
  milliseconds. The system is therefore asynchronous and job-based, not
  request-response (NFR-01).

- **A mandatory human gate.** Rendering must not begin until a human
  approves the proposed cut (FR-19). The pipeline pauses mid-flow and
  waits for an external event.

- **Resumability.** A user can close the tab and return; a failed stage
  must not discard completed work (FR-25, NFR-07). State is persisted at
  every stage boundary.

- **Swappable engines.** Transcription, the LLM, and the renderer are
  external capabilities accessed through interfaces, so they can be
  replaced without touching pipeline logic (keeps OQ-02 open).

## 2. System Context

The platform sits between its users and a small set of external
capabilities. Users supply three artefacts and review a proposed cut;
the system depends on a transcription engine, an LLM (Claude), and a
media-processing engine (FFmpeg).

| **External entity**        | **Direction** | **Interaction**                                                              |
|----------------------------|---------------|------------------------------------------------------------------------------|
| Content creator / reviewer | In / out      | Uploads video, deck, summary; reviews and approves the cut; downloads output |
| Transcription engine       | Out           | Audio → timestamped transcript with word-level timings and silence points    |
| Claude (LLM)               | Out           | Key points + transcript → proposed clip list as structured JSON              |
| Media engine (FFmpeg)      | Out           | Approved clip list → cut, concatenated, captioned MP4                        |
| Notification channel       | Out           | Tells the user when the cut is ready for review or rendering is complete     |

## 3. Logical Architecture

The system is organised into five layers. Each layer depends only on the
layer below it, and the processing pipeline reaches external engines
through the AI/ML services layer rather than calling them directly.

| **Layer**                 | **Responsibility**                  | **Key components**                                                                                  |
|---------------------------|-------------------------------------|-----------------------------------------------------------------------------------------------------|
| Presentation              | User-facing screens                 | Upload, processing/status, clip review & approval, output/download                                  |
| Application               | Orchestration, APIs, state          | API gateway, job orchestrator, project/status service, notification service                         |
| Processing pipeline       | The six core stages                 | Transcription, content extraction, segment selection, boundary snapping, caption generation, render |
| AI/ML & external services | Swappable engines behind interfaces | Transcription provider, Claude (LLM), FFmpeg, document parsers                                      |
| Data                      | Persistence                         | Object storage (media), metadata DB, transcript & clip-list store, job queue                        |

*A diagram of this layering and of the pipeline data flow accompanies
this document (see the two architecture diagrams produced alongside it).
The critical control point is the human approval gate, which sits
between segment selection and rendering.*

## 4. Component Breakdown

Each component has a single responsibility and a defined interface.
Components communicate through the orchestrator and the data layer, not
directly with one another.

### 4.1 API gateway

The single entry point for the frontend. Authenticates requests,
validates payloads, and routes to the orchestrator or project service.
Owns no business logic.

### 4.2 Job orchestrator

The heart of the application layer. Creates jobs, advances them stage by
stage, enqueues work for the pipeline workers, enforces the approval
gate as a hard pause (FR-19), and handles per-stage retry (NFR-07). It
is the only component that knows the full pipeline sequence.

### 4.3 Project & status service

Owns project records and exposes current state for the processing screen
(FR-24) and for resuming a project later (FR-25). Read-optimised; the
orchestrator writes state, this service serves it.

### 4.4 Pipeline workers

Stateless workers that each execute one pipeline stage, pull from the
job queue, call the relevant engine through its interface, write results
to the data layer, and report completion to the orchestrator. Workers
can scale independently — transcription and render workers are the heavy
ones.

### 4.5 Notification service

Sends the “ready for review” and “render complete” signals (FR-24) so
the user can leave the processing screen and return.

## 5. Data Model

Seven core entities. An ER diagram in mermaid form accompanies this
document; the entities and relationships are:

| **Entity** | **Holds**                                                                                 | **Key relationships**                                                    |
|------------|-------------------------------------------------------------------------------------------|--------------------------------------------------------------------------|
| Project    | Title, owner, target duration, vocabulary list, status                                    | Has many media assets; has one transcript, one clip list, one render job |
| MediaAsset | Type (video/deck/summary), storage URI, size, format                                      | Belongs to a project                                                     |
| Transcript | Timestamped text, word timings, silence points                                            | Belongs to a project; produced by transcription stage                    |
| KeyPoint   | Extracted point, source (deck slide / summary)                                            | Belongs to a project; mapped to segments                                 |
| Segment    | Source start/end, duration, transcript snippet, confidence, mapped key point, locked flag | Belongs to a clip list                                                   |
| ClipList   | Ordered segments, total duration, coverage state, approval status                         | Belongs to a project; reviewed at the gate                               |
| RenderJob  | Status, output URI, resolution, caption URI, size                                         | Belongs to a project; produced after approval                            |

*Note: the locked flag on Segment and the coverage state on ClipList are
design decisions from the Claude Design pass (segment locking, key-point
coverage panel) not yet in requirements v0.1 — flagged for back-fill.*

## 6. Pipeline Orchestration

A job moves through the stages below. Transcription and content
extraction run in parallel and converge at segment selection. The job
then pauses at the approval gate and does not resume until an approval
event arrives.

| **\#** | **Stage**             | **Input → output**                         | **On failure (NFR-07)**                       |
|--------|-----------------------|--------------------------------------------|-----------------------------------------------|
| 1      | Transcription         | Video → timestamped transcript             | Retry; completed uploads preserved            |
| 2      | Content extraction    | Deck + summary → key points                | Retry independently of (1)                    |
| 3      | Segment selection     | Key points + transcript → clip list (JSON) | Retry; validate JSON, re-prompt on bad output |
| 4      | Approval gate (pause) | Clip list → reviewer decision              | No timeout; waits for human (FR-16–19)        |
| 5      | Render                | Approved clip list → MP4 + captions        | Retry; transcript & clip list preserved       |

### 6.1 The approval gate

When segment selection completes, the orchestrator persists the
candidate clip list, sets the job status to AWAITING_REVIEW, fires a
notification, and stops. The render stage is only enqueued when the
application layer receives an explicit approval (FR-19). The reviewer’s
edits — reorder, remove, boundary nudge, lock, and “re-edit cut” (which
re-runs selection while preserving locked segments) — mutate the
persisted clip list before approval.

### 6.2 State & resumability

Because each stage writes its output to the data layer before reporting
completion, a closed tab loses nothing (FR-25) and a failed stage
resumes from the last good state rather than from the start (NFR-07).
Job status is the single source of truth for which screen the user sees
on return.

## 7. Indicative API Surface

REST over HTTPS. Long-running operations return immediately with a
job/project ID; the frontend polls status or receives a notification.
Indicative endpoints:

| **Method & path**             | **Purpose**                                            |
|-------------------------------|--------------------------------------------------------|
| POST /projects                | Create a project, return upload targets (FR-01–06)     |
| POST /projects/{id}/assets    | Register an uploaded asset (video/deck/summary)        |
| POST /projects/{id}/start     | Begin processing once all three assets present (FR-04) |
| GET /projects/{id}/status     | Current stage & per-stage progress (FR-24)             |
| GET /projects/{id}/cliplist   | The proposed clip list for review (FR-16)              |
| PATCH /projects/{id}/cliplist | Apply reorder / remove / nudge / lock edits (FR-17)    |
| POST /projects/{id}/reedit    | Re-run selection, preserving locked segments           |
| POST /projects/{id}/approve   | Approve the cut and enqueue render (FR-19)             |
| GET /projects/{id}/output     | Render result: MP4, captions, metadata (FR-23)         |

*Uploads use pre-signed URLs direct to object storage so large video
files (FR-01) never pass through the application tier.*

## 8. Asynchronous Job Model

A queue decouples the API tier from the heavy workers. The flow for a
single job:

1. API tier validates the request and creates/advances the job record.

2. The orchestrator enqueues a stage task onto the job queue.

3. A free worker of the right type pulls the task and runs the stage.

4. The worker writes output to the data layer and acks the
    orchestrator.

5. The orchestrator advances the job and enqueues the next stage — or
    pauses at the gate.

Transcription and render worker pools scale independently of the API
tier (NFR-01, NFR-08), and a worker crash returns the task to the queue
rather than losing the job.

## 9. Claude Segment-Selection Contract

This is the core IP (FR-12–15). The call is deterministic in shape:
structured input in, strict JSON out, validated before use.

### 9.1 Input

- The extracted key points, each with its source (deck slide or summary
  line).

- The timestamped transcript with sentence/silence boundaries.

- Constraints: target duration (FR-14), and the instruction to snap
  boundaries to silence (FR-15).

### 9.2 Required output (strict JSON)

The model is instructed to return only JSON — no prose, no markdown fences — shaped as an ordered list of segments:

```json
{
  "segments": [
    {
      "start": "00:02:14",
      "end": "00:02:41",
      "transcript": "...",
      "key_point_id": "kp-03",
      "confidence": 0.92
    }
  ],
  "total_duration_sec": 204,
  "uncovered_key_points": ["kp-07", "kp-08"]
}
```

### 9.3 Validation & guardrails

- Parse strictly; on malformed JSON, re-prompt with the parse error
  (bounded retries), then surface a failure (NFR-07).

- Verify every timestamp exists in the transcript and lands on a known
  silence boundary (FR-15); otherwise snap server-side.

- Verify total duration is within the target (FR-14); if over, flag
  rather than silently truncate.

- uncovered_key_points drives the coverage panel and the
  approve-with-gaps confirmation (design-pass decision; flag for
  back-fill).

*Use Claude Sonnet for this task — it is sufficient and far cheaper than
Opus at this scale (NFR-02).*

## 10. Deployment Topology

Indicative; tuned for a repeatable product that can start small and
scale. All compute can begin on a single host and split out as load
grows (NFR-08).

| **Tier**             | **Runs**                                           | **Scaling note**                                      |
|----------------------|----------------------------------------------------|-------------------------------------------------------|
| Web / API            | Frontend, API gateway, project service             | Stateless; scale horizontally behind a load balancer  |
| Orchestrator + queue | Job orchestrator, job queue                        | Single logical orchestrator; durable queue            |
| Worker pool          | Pipeline workers (transcription, render heaviest)  | Scale per stage; GPU optional for local transcription |
| Data                 | Object storage, metadata DB, transcript/clip store | Managed services preferred for durability             |

*Transcription is deliberately abstracted behind an interface, so OQ-02
(self-hosted Whisper vs hosted API) is a worker-configuration choice,
not an architectural one.*

## 11. Cross-Cutting Concerns

| **Concern**   | **Approach**                                                                   | **Req**      |
|---------------|--------------------------------------------------------------------------------|--------------|
| Security      | AuthN at the gateway; signed URLs for media; least-privilege access to storage | NFR-05       |
| Privacy       | Source media not used to train third-party models; retention policy on storage | NFR-06       |
| Cost          | Sonnet for selection; local or batched transcription; compute-only render      | NFR-02       |
| Reliability   | Stage-level persistence + retry; queue redelivery on worker crash              | NFR-07       |
| Observability | Per-stage status, durations, and job IDs surfaced to the UI and logs           | FR-24        |
| Accuracy      | Custom vocabulary to transcription; server-side boundary snapping              | FR-08, FR-15 |

## 12. Decisions to Back-Fill into Requirements

These emerged during the design and architecture passes and should be
added to the Requirements Specification (proposed v0.2):

- Segment locking, and “re-edit cut” preserving locked segments (extends
  FR-17).

- Key-point coverage tracking and gaps panel (new FR).

- Approve-with-gaps confirmation before render (extends FR-19).

- Undo on segment removal (extends FR-17).

- Boundary nudges of ±0.5s snapped to silence (clarifies FR-15).

- Stage failure with retry, preserving completed work (clarifies
  NFR-07).

- Output resolution choice and SRT caption download (extends FR-21,
  FR-23).

*I can produce requirements v0.2 with these folded in as tracked changes
whenever you want.*
