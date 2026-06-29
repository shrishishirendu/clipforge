"""Transcription providers, behind the TranscriptionProvider interface (arch §10).

Default is local Whisper via faster-whisper; hosted providers (Deepgram,
AssemblyAI) can be added here without touching pipeline code (OQ-02). The factory
picks the implementation from settings.transcription_provider.
"""
from __future__ import annotations

from functools import lru_cache

from app.core import winshim  # noqa: F401 — applies the Windows/Anaconda shutil.move shim
from app.core.config import settings


@lru_cache
def _load_whisper_model(model_size: str, compute_type: str):
    """Load (and cache) a faster-whisper model. Imported lazily so this module
    loads even where faster-whisper isn't installed (e.g. an API-only deploy
    configured for a hosted provider). Cached so a worker reuses it across jobs."""
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device="cpu", compute_type=compute_type)


class LocalWhisperProvider:
    """faster-whisper. Decodes audio directly from the (video) file via PyAV, so
    no system FFmpeg is required. Returns word-level timings and silence points
    (FR-07, FR-09); the custom vocabulary biases names/jargon (FR-08)."""

    def __init__(self, model_size: str | None = None, compute_type: str | None = None,
                 silence_gap_sec: float | None = None):
        self._model_size = model_size or settings.whisper_model
        self._compute_type = compute_type or settings.whisper_compute_type
        self._silence_gap = (settings.silence_gap_sec if silence_gap_sec is None
                             else silence_gap_sec)

    def transcribe(self, audio_uri: str, vocabulary: list[str]) -> dict:
        model = _load_whisper_model(self._model_size, self._compute_type)
        initial_prompt = ", ".join(vocabulary) if vocabulary else None  # FR-08
        segments, _info = model.transcribe(
            audio_uri,
            word_timestamps=True,
            vad_filter=True,
            initial_prompt=initial_prompt,
        )

        words: list[dict] = []
        texts: list[str] = []
        for seg in segments:  # generator — consuming it runs the transcription
            text = seg.text.strip()
            if text:
                texts.append(text)
            for w in (seg.words or []):
                # cast np.float64 -> native float for clean JSON storage
                words.append({"word": w.word.strip(),
                              "start": round(float(w.start), 3),
                              "end": round(float(w.end), 3)})

        return {
            "full_text": " ".join(texts),
            "word_timings": words,
            "silence_points": self._silence_points(words),
        }

    def _silence_points(self, words: list[dict]) -> list[float]:
        """Clean cut points (FR-09, FR-15): the clip start, the clip end, and the
        midpoint of every inter-word gap >= the configured silence threshold."""
        if not words:
            return []
        points = [round(words[0]["start"], 3)]
        for prev, nxt in zip(words, words[1:]):
            if nxt["start"] - prev["end"] >= self._silence_gap:
                points.append(round((prev["end"] + nxt["start"]) / 2, 3))
        points.append(round(words[-1]["end"], 3))
        return points


def get_transcription_provider():
    """Factory: the transcription engine configured in settings (arch §10, OQ-02)."""
    name = settings.transcription_provider
    if name == "whisper_local":
        return LocalWhisperProvider()
    raise ValueError(
        f"unsupported transcription provider '{name}'; "
        "only 'whisper_local' is implemented (Deepgram/AssemblyAI planned, OQ-02)"
    )
