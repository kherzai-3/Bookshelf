---
source: tests/test_eval.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 2714a5be6632b40341d4070940b797fa1c956f15
---

## Purpose
Covers `eval.py`: `groundedness_score` on supported vs. unsupported
statements, `run_eval`'s read-only guarantee (no `facts.jsonl`/
`entities.json` written), parse-failure tracking via a local
`_AlwaysFailsProvider` test double, and `summarize`'s per-provider fact
counts.
