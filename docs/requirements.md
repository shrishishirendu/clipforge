# Requirements Specification — AI Video Summarisation Platform

_AI Video Summarisation & Auto-Editing Platform_

*Working name: “ClipForge” (placeholder)*

| **Field**            | **Value**                           |
|----------------------|-------------------------------------|
| Document owner       | Head of Data & AI, iSOFT            |
| Status               | DRAFT — for review & sign-off       |
| Version              | 0.1                                 |
| Date                 | 28 June 2026                        |
| Classification       | Internal — iSOFT                    |
| Target build profile | Tier B — Human-in-the-loop approval |

Contents

## 1. Document Control

### 1.1 Purpose of this document

This document captures and locks the agreed requirements for the AI
Video Summarisation & Auto-Editing Platform. It is the single source of
truth for scope. Any change to scope must be reflected here via the
revision history before it is treated as agreed.

### 1.2 Revision history

| **Version** | **Date**    | **Author**        | **Summary of change**    |
|-------------|-------------|-------------------|--------------------------|
| 0.1         | 28 Jun 2026 | Head of Data & AI | Initial draft for review |
|             |             |                   |                          |
|             |             |                   |                          |

### 1.3 Approval

| **Name** | **Role**       | **Signature / approval** | **Date** |
|----------|----------------|--------------------------|----------|
|          | Product owner  |                          |          |
|          | Technical lead |                          |          |
|          | Stakeholder    |                          |          |

## 2. Product Overview

### 2.1 Problem statement

Recordings of talks, lectures, and presentations are typically 30–90
minutes long. Audiences increasingly want a tight 3–4 minute version
that conveys the key points. Producing this manually is slow and
requires video-editing skill. The platform automates the bulk of this
work while keeping a human approval step to guarantee quality.

### 2.2 Solution summary

A user uploads three artefacts — the full video, the presentation deck,
and a document containing the key points / summary of the talk. The
system transcribes the video, uses the supplied deck and summary as an
editorial guide to select the most relevant segments, proposes a clip
list for human approval, and on approval renders a polished 3–4 minute
edited video with captions.

### 2.3 Goals

- Reduce production effort for a short-form cut to roughly five minutes
  of human review per video.

- Use the user’s own summary/deck as the editorial guide rather than
  generic “virality” heuristics.

- Keep marginal cost per video negligible (target under USD 1).

- Produce client-presentable output, not just rough drafts.

### 2.4 Non-goals (explicitly out of scope for v1)

- Generating new footage, avatars, or voiceover (no synthetic
  video/audio generation).

- Multi-speaker diarisation and per-speaker editing.

- Real-time / live-stream editing.

- Full timeline NLE-style manual video editing inside the tool (only
  clip-boundary nudging is in scope).

- Translation or dubbing into other languages.

## 3. Users & Stakeholders

| **Role**            | **Description**                                       | **Primary need**                               |
|---------------------|-------------------------------------------------------|------------------------------------------------|
| Content creator     | Uploads source material, reviews and approves the cut | Fast, low-effort production of a quality short |
| Reviewer / approver | Optional second pair of eyes before publishing        | Confidence the cut is accurate and on-message  |
| Administrator       | Manages access, vocabulary lists, settings            | Control and consistency across the team        |

## 4. Functional Requirements

*Each requirement carries a unique ID (FR-xx) and a priority: M =
Must-have (v1), S = Should-have, C = Could-have (future).*

### 4.1 Input & upload

| **ID** | **Requirement**                                                                               | **Pri** |
|--------|-----------------------------------------------------------------------------------------------|---------|
| FR-01  | The system shall accept a video file upload (MP4, MOV, common codecs).                        | M       |
| FR-02  | The system shall accept a presentation file (.pptx, .pdf).                                    | M       |
| FR-03  | The system shall accept a summary / key-points document (.docx, .pdf, .txt).                  | M       |
| FR-04  | The system shall validate file types and size on upload and report errors clearly.            | M       |
| FR-05  | The system shall support a target output duration parameter (default 3–4 min, configurable).  | M       |
| FR-06  | The system shall accept an optional custom vocabulary / glossary list (names, product terms). | S       |

### 4.2 Transcription

| **ID** | **Requirement**                                                                            | **Pri** |
|--------|--------------------------------------------------------------------------------------------|---------|
| FR-07  | The system shall transcribe the video to text with word-level timestamps.                  | M       |
| FR-08  | The system shall apply the custom vocabulary list to improve accuracy of names and jargon. | S       |
| FR-09  | The system shall detect silence / sentence boundaries for use as clean cut points.         | M       |

### 4.3 Content extraction

| **ID** | **Requirement**                                                         | **Pri** |
|--------|-------------------------------------------------------------------------|---------|
| FR-10  | The system shall extract key points and text from the supplied deck.    | M       |
| FR-11  | The system shall extract key points from the supplied summary document. | M       |

### 4.4 Segment selection (core IP)

| **ID** | **Requirement**                                                                                                           | **Pri** |
|--------|---------------------------------------------------------------------------------------------------------------------------|---------|
| FR-12  | The system shall use an LLM to map the supplied key points to the best-matching transcript segments.                      | M       |
| FR-13  | The system shall return a candidate clip list as structured data (start/end timestamps + transcript snippet + rationale). | M       |
| FR-14  | The system shall keep the total selected duration within the target output duration.                                      | M       |
| FR-15  | The system shall snap all proposed cut points to the nearest sentence/silence boundary.                                   | M       |

### 4.5 Human-in-the-loop review (Tier B)

| **ID** | **Requirement**                                                                        | **Pri** |
|--------|----------------------------------------------------------------------------------------|---------|
| FR-16  | The system shall present the proposed clip list to the user before rendering.          | M       |
| FR-17  | The user shall be able to approve, remove, reorder, and nudge the boundaries of clips. | M       |
| FR-18  | The system shall recalculate total duration as the user edits the clip list.           | M       |
| FR-19  | The system shall not render until the user explicitly approves the clip list.          | M       |

### 4.6 Rendering & output

| **ID** | **Requirement**                                                                 | **Pri** |
|--------|---------------------------------------------------------------------------------|---------|
| FR-20  | The system shall cut and concatenate the approved segments into a single video. | M       |
| FR-21  | The system shall generate burned-in or sidecar captions for the final cut.      | S       |
| FR-22  | The system shall allow an optional intro/outro and simple branding (logo).      | C       |
| FR-23  | The system shall output a standard MP4 and provide a download link.             | M       |

### 4.7 Management

| **ID** | **Requirement**                                                         | **Pri** |
|--------|-------------------------------------------------------------------------|---------|
| FR-24  | The system shall show processing status/progress for each stage.        | S       |
| FR-25  | The system shall retain projects so a user can return and re-render.    | S       |
| FR-26  | The system shall allow management of the shared custom vocabulary list. | C       |

## 5. Non-Functional Requirements

| **ID** | **Category** | **Requirement**                                                                                                                              |
|--------|--------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| NFR-01 | Performance  | End-to-end processing (excluding human review) of a 60-min video should complete within a reasonable batch window (target \< 15 min on GPU). |
| NFR-02 | Cost         | Marginal inference + transcription cost per video shall remain under USD 1.                                                                  |
| NFR-03 | Accuracy     | Captions shall be reviewable and correctable; cut points shall not land mid-word.                                                            |
| NFR-04 | Usability    | A non-technical user shall be able to complete a project without editing skills.                                                             |
| NFR-05 | Security     | Uploaded media and transcripts shall be access-controlled; no public exposure by default.                                                    |
| NFR-06 | Privacy      | Source material shall not be used to train third-party models; data handling to follow iSOFT policy.                                         |
| NFR-07 | Reliability  | Failure in any stage shall surface a clear error and preserve already-completed work.                                                        |
| NFR-08 | Portability  | The system shall run on existing iSOFT infrastructure or a single cloud VM.                                                                  |

## 6. Solution Architecture (Indicative)

The reference pipeline is:

## 1. Upload — video, deck, and summary document.

## 2. Transcription — Whisper produces a timestamped transcript with
    silence/sentence boundaries.

## 3. Extraction — deck and summary parsed into key points (python-pptx,
    python-docx / PDF parsing).

## 4. Segment selection — LLM maps key points to transcript segments and
    returns a clip list as JSON.

## 5. Review — the clip list is presented for human approval, editing, and
    boundary nudging.

## 6. Render — FFmpeg cuts, snaps to boundaries, concatenates, adds
    captions, and outputs MP4.

### 6.1 Indicative technology stack

| **Layer**         | **Technology**              | **Notes**                       |
|-------------------|-----------------------------|---------------------------------|
| Frontend          | React / Next.js             | Upload + clip-review UI         |
| Backend           | FastAPI (Python)            | Orchestration & APIs            |
| Transcription     | Whisper (local or API)      | Word-level timestamps           |
| Segment selection | Claude (Sonnet)             | Opus not required for this task |
| Deck/doc parsing  | python-pptx, python-docx    | Plus PDF parsing                |
| Video processing  | FFmpeg                      | Cut, snap, concat, captions     |
| Storage / DB      | PostgreSQL + object storage | Projects, media, transcripts    |

*Note: the technology stack is indicative and may change during
implementation. Functional and non-functional requirements above are the
binding part of this specification.*

## 7. Assumptions, Dependencies & Constraints

### 7.1 Assumptions

- Source video has reasonably clear audio suitable for transcription.

- The supplied summary/deck genuinely reflect the key points the user
  wants emphasised.

- A human will review every client-facing output before publishing.

### 7.2 Dependencies

- Availability of the Anthropic API for segment selection.

- Compute (CPU or GPU) for transcription and rendering.

### 7.3 Constraints

- Output target duration is 3–4 minutes by default.

- v1 is single-language and single-pipeline (no live editing).

## 8. Acceptance Criteria

The v1 product is accepted when:

- A user can upload video + deck + summary and reach a proposed clip
  list without manual intervention.

- The proposed cut reflects the supplied key points and stays within the
  target duration.

- All cut points land on sentence/silence boundaries (no mid-word cuts).

- The user can approve/edit the clip list and the system renders a
  downloadable MP4 with captions.

- Typical human effort per video is approximately five minutes of
  review, with no video editing required.

## 9. Indicative Effort & Cost

*Provided for planning only; not part of the locked functional scope.*

### 9.1 Build effort (one experienced engineer)

| **Component**                        | **Effort**          |
|--------------------------------------|---------------------|
| Upload + storage                     | 0.5 day             |
| Transcription + timestamps           | 1 day               |
| Deck/doc parsing                     | 0.5 day             |
| LLM segment selection (core IP)      | 1.5–2 days          |
| FFmpeg cut/concat + silence-snapping | 1.5 days            |
| Review/approval UI                   | 1.5–2 days          |
| Captions + render + output           | 1 day               |
| Glue, error handling, testing        | 1 day               |
| Total (with buffer)                  | ~8–12 calendar days |

### 9.2 Running cost

- Transcription: free locally, or ~USD 0.30–0.40/hour of audio via API.

- Segment selection (Claude Sonnet): ~USD 0.05–0.15 per video.

- Rendering: compute only — cents per video.

- Marginal cost per video: typically under USD 1.

- Fixed infrastructure: ~USD 0 on existing kit, or ~USD 50–150/month for
  a dedicated GPU VM.

## 10. Open Questions / To Be Decided

| **ID** | **Question**                               | **Owner** | **Status** |
|--------|--------------------------------------------|-----------|------------|
| OQ-01  | One-off use or repeatable iSOFT product?   |           | Open       |
| OQ-02  | Local Whisper or hosted transcription API? |           | Open       |
| OQ-03  | Captions burned-in, sidecar SRT, or both?  |           | Open       |
| OQ-04  | Branding / intro-outro required for v1?    |           | Open       |
| OQ-05  | Where is media stored and for how long?    |           | Open       |

## 11. Future Scope (Backlog)

- Multiple output lengths from one source (e.g. 1-min, 3-min, 10-min).

- Auto-generated titles, descriptions, and social captions.

- B-roll insertion from deck slides aligned to spoken content.

- Multi-speaker diarisation.

- Translation / multilingual captions.

- Direct publish to YouTube / LinkedIn.
