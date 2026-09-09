---
source: src/bookrag/providers/registry.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 62d98e276ecbe8adfb3429301976083a445c1b8d
---

## Purpose
Single place that turns a provider name (CLI flag or `$BOOKRAG_PROVIDER`)
into a `Provider` instance - the `cli.py extract`/`eval` commands go through
this rather than importing a specific provider directly.

## Public Interface
- `DEFAULT_PROVIDER = "ollama"` — the practical default: no API key
  required. Changed from `"anthropic"` since a standalone script needs its
  own direct API/Bedrock/Vertex credential - separate from whatever
  authenticates a developer's Claude Code/Claude.ai access - and Ollama
  needs no credential at all.
- `get_provider(name: str | None = None, model: str | None = None) ->
  Provider` — `name` defaults to `$BOOKRAG_PROVIDER` then
  `DEFAULT_PROVIDER`. Raises `ValueError` for anything other than
  `"anthropic"`, `"ollama"`, `"fake"`. `model`, if given, is forwarded to
  the provider's constructor (letting `cli.py`'s `--model` flag override
  the provider's own default/env-var model); silently ignored for
  `"fake"`, which has no underlying model to select.

## Key Decisions
- Provider modules are imported lazily, inside each branch - so
  `get_provider("fake")` never imports `anthropic_provider.py` (and
  therefore never requires an API key or even the `anthropic` package to be
  importable) purely because it happened to be listed first. Same reasoning
  keeps `ollama_provider.py` from being imported when picking `"fake"` or
  `"anthropic"`.

## Dependencies
- Internal: `bookrag.providers.anthropic_provider.AnthropicProvider`,
  `bookrag.providers.ollama_provider.OllamaProvider`,
  `bookrag.providers.fake_provider.FakeProvider` (all three lazy)
