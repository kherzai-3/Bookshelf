---
source: tests/test_fake_provider.py
last_synced: 2026-09-02T00:00:00Z
source_hash: d078a2a6c3951c35fc7fe3d1760f25eb6ef0d5ce
---

## Purpose
Covers `FakeProvider`'s deterministic behavior: one fact per new
capitalized word, repeats deduplicated, common stopword-starters ("The",
"He", ...) not treated as entities.
