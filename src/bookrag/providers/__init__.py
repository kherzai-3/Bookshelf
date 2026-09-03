"""Pluggable LLM providers for fact extraction (Claude today; a local model
and a deterministic fake for tests)."""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    # Loaded here, not in a specific provider module, so a .env-defined
    # ANTHROPIC_API_KEY/OLLAMA_MODEL/etc. is picked up regardless of which
    # provider ends up being used - any provider is reached through this
    # package, but a script that only ever uses OllamaProvider would never
    # import anthropic_provider.py, which is where this used to live.
    load_dotenv()
except ImportError:
    pass
