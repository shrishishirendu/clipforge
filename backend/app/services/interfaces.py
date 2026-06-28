"""Provider interfaces. Transcription, LLM, and media engines sit behind these
so they can be swapped without touching pipeline logic (architecture §1, §10)."""
from __future__ import annotations

from typing import Protocol


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
