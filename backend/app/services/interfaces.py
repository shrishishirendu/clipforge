"""Provider interfaces. Transcription, LLM, media, and object storage sit behind
these so they can be swapped without touching route/pipeline logic (arch §1, §10)."""
from __future__ import annotations

from typing import Protocol


class ObjectStorage(Protocol):
    """S3-compatible object storage. The S3/MinIO impl is the default; tests use
    an in-memory fake. Routes never construct a boto3 client directly (arch §7)."""

    def presigned_put_url(self, key: str, expires_in: int = 3600) -> str:
        """A URL the client PUTs the file to, direct to storage (bypasses the app tier)."""
        ...

    def stat(self, key: str) -> dict | None:
        """Return {"size_bytes": int} if the object exists, else None (for the
        asset-complete callback to confirm the upload landed)."""
        ...


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_uri: str, vocabulary: list[str]) -> dict:
        """Return {full_text, word_timings:[{word,start,end}], silence_points:[sec,...]}.
        Implementations: local Whisper, Deepgram, AssemblyAI (OQ-02)."""
        ...


class MediaEngine(Protocol):
    def cut_and_concat(self, source_uri: str, segments: list[dict],
                       captions: list[dict] | None, resolution: str) -> dict:
        """Cut the source at segment boundaries, concat, burn/sidecar captions.
        Return {output_uri, caption_uri, size_bytes}. Implementation: FFmpeg."""
        ...
