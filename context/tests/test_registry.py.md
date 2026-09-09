---
source: tests/test_registry.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 9b883e3f67e2d8a048ab85369931cb6dfb9beaf4
---

## Purpose
Covers `providers.registry.get_provider`: unknown provider name raises,
`model` is ignored (no error) for `"fake"`, and the ollama model-resolution
order (`model` arg > `$OLLAMA_MODEL` > `OllamaProvider.DEFAULT_MODEL`). Also
covers `OllamaProvider`'s `num_ctx` resolution directly (constructed
without going through `get_provider`, which doesn't thread `num_ctx`
through): defaults to `DEFAULT_NUM_CTX` with no env var set, falls back to
`$OLLAMA_NUM_CTX` when one is.

## Key Decisions
- Reaches into `provider._model` (a "private" attribute) to verify
  constructor wiring directly - there's no public getter, and this is the
  simplest way to confirm the override actually took effect.
