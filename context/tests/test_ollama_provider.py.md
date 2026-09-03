---
source: tests/test_ollama_provider.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 881e3ec4ca54c21f7a7a702757db0dbb30dd9dec
---

## Purpose
Real integration smoke test against a locally-running Ollama - not a unit
test. Skipped (not failed) via `pytest.mark.skipif` when Ollama isn't
reachable at `$OLLAMA_BASE_URL`/`localhost:11434`, so the main suite stays
green on a machine without it, while this one actually exercises the real
model where it's available.

## Key Decisions
- Only asserts the response parsed into well-formed `ExtractedFact`s - a
  real LLM's exact content isn't asserted (non-deterministic), just that
  the pipeline (network call → `format: "json"` → `parse_facts`) works
  end-to-end without raising.
