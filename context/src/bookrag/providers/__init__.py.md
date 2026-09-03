---
source: src/bookrag/providers/__init__.py
last_synced: 2026-09-03T00:00:00Z
source_hash: a4a81eaaa5ed3684720d9c9451c44ea6af30bebf
---

## Purpose
Package marker for `bookrag.providers` - pluggable LLM backends for fact
extraction (Claude, a local Ollama model, and a deterministic fake for
tests).

## Key Decisions
- Loads `.env` (via `python-dotenv`, best-effort) at package-import time,
  not inside a specific provider module. Previously lived only in
  `anthropic_provider.py`, which meant a `.env`-defined `OLLAMA_MODEL` (or
  anything else) would never be read on a run that only ever uses
  `OllamaProvider` and never imports the Anthropic module. Any provider is
  reached through this package, so loading here covers all of them.
