---
source: tests/test_titles.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 37b322966ab72cdf8187ca5ca5e85e732965a778
---

## Purpose
Covers `titles.guess_title_author`: the `"... by ..."` split, the no-match
fallback, and separator/whitespace collapsing.

## Key Decisions
- `test_splits_title_and_author_on_by` uses the exact real filename
  (`Finite-and-Infinite-Games-by-James-Carse`) found while testing ingestion
  against a real PDF with no internal metadata - not a made-up example.
