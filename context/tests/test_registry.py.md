---
source: tests/test_registry.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 71043c5167682ccb1449262aa9bdc63ee4adee2f
---

## Purpose
Covers `providers.registry.get_provider`: unknown provider name raises,
`model` is ignored (no error) for `"fake"`, and the ollama model-resolution
order (`model` arg > `$OLLAMA_MODEL` > `OllamaProvider.DEFAULT_MODEL`),
including the no-override-no-env-var default case. Also covers that
`self._answer_model` (chat's independent model knob - see
`ollama_provider.py`'s context doc) resolves separately from `self._model`
via its own `$OLLAMA_ANSWER_MODEL`/`DEFAULT_ANSWER_MODEL`, while a single
constructor `model` override still applies to both. Also covers
`OllamaProvider`'s `num_ctx` resolution directly (constructed without going
through `get_provider`, which doesn't thread `num_ctx` through): defaults
to `DEFAULT_NUM_CTX` with no env var set, falls back to `$OLLAMA_NUM_CTX`
when one is.

## Key Decisions
- Reaches into `provider._model` (a "private" attribute) to verify
  constructor wiring directly - there's no public getter, and this is the
  simplest way to confirm the override actually took effect.
