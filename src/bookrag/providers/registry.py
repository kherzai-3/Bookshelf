"""Provider lookup by name. Imports are lazy so picking one provider never
requires another's dependencies (anthropic SDK/API key, Ollama running) to
be available."""

from __future__ import annotations

import os

from bookrag.providers.base import Provider

DEFAULT_PROVIDER = "ollama"  # no API key needed - the practical default here


def get_provider(name: str | None = None, model: str | None = None) -> Provider:
    """`model` overrides the provider's own default/env-var model (e.g. pick
    a bigger Ollama model on a machine with a GPU). Ignored for "fake",
    which has no underlying model to select."""
    name = name or os.environ.get("BOOKRAG_PROVIDER", DEFAULT_PROVIDER)

    if name == "anthropic":
        from bookrag.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(model=model)
    if name == "ollama":
        from bookrag.providers.ollama_provider import OllamaProvider

        return OllamaProvider(model=model)
    if name == "fake":
        from bookrag.providers.fake_provider import FakeProvider

        return FakeProvider()
    raise ValueError(f"Unknown provider: {name!r} (expected 'anthropic', 'ollama', or 'fake')")
