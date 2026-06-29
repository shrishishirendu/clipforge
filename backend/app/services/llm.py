"""LLM providers behind the LLMProvider interface (arch §10). Default is Claude
Sonnet (settings.segment_selection_model) — sufficient for segment selection and
far cheaper than Opus at this scale (NFR-02)."""
from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


class AnthropicLLM:
    """Thin wrapper over the Anthropic Messages API."""

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — required for segment selection (B5)")
        from anthropic import Anthropic  # lazy import keeps the module light
        self._client = Anthropic(api_key=api_key)
        self._model = model

    def complete(self, system: str, user: str, max_tokens: int = 4000) -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


@lru_cache
def get_llm_provider() -> AnthropicLLM:
    """Factory: the configured LLM (arch §10). Built once per process."""
    return AnthropicLLM(settings.anthropic_api_key, settings.segment_selection_model)
