"""Shared test doubles for the pipeline (fake transcription, parsing, LLM)."""

# A small canned transcript with silence points, reused across pipeline tests.
CANNED_TRANSCRIPT = {
    "full_text": "hello world this is a talk",
    "word_timings": [
        {"word": "hello", "start": 0.0, "end": 0.4},
        {"word": "world", "start": 0.5, "end": 0.9},
        {"word": "talk", "start": 2.0, "end": 2.4},
    ],
    "silence_points": [0.0, 1.45, 2.4],
}


class FakeTranscriptionProvider:
    def __init__(self, result=None):
        self.result = result or CANNED_TRANSCRIPT
        self.calls = []

    def transcribe(self, audio_uri, vocabulary):
        self.calls.append((audio_uri, list(vocabulary)))
        return self.result


class FakeDocumentParser:
    """Returns one key point per parsed asset, tagged with the asset type."""

    def __init__(self):
        self.calls = []

    def extract_key_points(self, path, asset_type, ext):
        self.calls.append((path, asset_type, ext))
        return [{"text": f"key point from {asset_type}", "source": asset_type}]


class FakeLLM:
    """Returns queued responses in order; records prompts for assertions."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, system, user, max_tokens=4000):
        self.calls.append((system, user))
        return self.responses.pop(0)
