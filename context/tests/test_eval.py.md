---
source: tests/test_eval.py
last_synced: 2026-09-13T16:40:00Z
source_hash: 0737cf72add0deaca6b991bce7039918816a91e4
---

## Purpose
Covers `eval.py`: `groundedness_score` on supported vs. unsupported
statements, `run_eval`'s read-only guarantee (no `facts.jsonl`/
`entities.json` written), parse-failure tracking via a local
`_AlwaysFailsProvider` test double, and `summarize`'s per-provider fact
counts.
