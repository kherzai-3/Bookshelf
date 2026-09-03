---
source: tests/test_registry.py
last_synced: 2026-09-03T00:00:00Z
source_hash: fa3a5858fb27827ac2b4f5aebdb6c3022b9fd585
---

## Purpose
Covers `providers.registry.get_provider`: unknown provider name raises,
`model` is ignored (no error) for `"fake"`, and the ollama model-resolution
order (`model` arg > `$OLLAMA_MODEL` > `OllamaProvider.DEFAULT_MODEL`).

## Key Decisions
- Reaches into `provider._model` (a "private" attribute) to verify
  constructor wiring directly - there's no public getter, and this is the
  simplest way to confirm the override actually took effect.
