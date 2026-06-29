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

    def download_to_path(self, key: str, dest_path: str) -> None:
        """Download the object to a local path (workers pull media to process it)."""
        ...

    def upload_file(self, local_path: str, key: str, content_type: str | None = None) -> None:
        """Upload a local file (render outputs: MP4, SRT) to storage."""
        ...

    def presigned_get_url(self, key: str, expires_in: int = 3600) -> str:
        """A time-limited download URL for an object (the output MP4/captions)."""
        ...


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_uri: str, vocabulary: list[str]) -> dict:
        """Return {full_text, word_timings:[{word,start,end}], silence_points:[sec,...]}.
        Implementations: local Whisper, Deepgram, AssemblyAI (OQ-02)."""
        ...


class MediaEngine(Protocol):
    """Video processing behind FFmpeg. Works on local files; the worker handles
    storage download/upload (keeps FFmpeg decoupled from object storage)."""

    def render(self, source_path: str, segments: list[dict], output_path: str,
               resolution: str = "1080p") -> dict:
        """Cut source_path at each segment's [start_sec, end_sec], concat in order
        into output_path (MP4). Return {"size_bytes": int}. (Sidecar captions are
        built separately, services/captions.py.)"""
        ...


class LLMProvider(Protocol):
    """The LLM behind a thin text-completion call (arch §1, §4 rule). The segment-
    selection prompt + JSON validation + snapping live in services/segment_selection
    (the IP); only the raw model call is swapped here. Default: Claude Sonnet."""

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        """Return the model's text response for the given system + user prompt."""
        ...


class DocumentParser(Protocol):
    """Extracts key points from a deck/summary file (FR-10, FR-11). Default impl
    uses python-pptx / python-docx / pypdf; tests use a fake."""

    def extract_key_points(self, path: str, asset_type: str, ext: str) -> list[dict]:
        """Return [{"text": str, "source": str}] from the document at `path`."""
        ...
