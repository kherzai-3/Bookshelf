---
source: tests/test_consolidate.py
last_synced: 2026-09-08T00:00:00Z
source_hash: e31c416e8b4f186772439ff8593d633281abfdb0
---

## Purpose
Verifies `bookrag.ingest.consolidate`'s trigger decision (`should_consolidate`)
and merge logic (`consolidate_fragments`) directly against hand-built
`Chapter` objects - no synthetic epub needed, since this module is a pure
`list[Chapter] -> list[Chapter]` transformation.

## Key Decisions
- `_chapter(index, word_count, title=None)` builds a `Chapter` whose text is
  exactly `word_count` space-separated tokens, so word-count-threshold
  assertions are exact rather than approximate.
- `test_should_consolidate_is_not_skewed_by_a_few_outliers` is the one test
  directly encoding *why* the trigger uses the median rather than the mean
  - nine 300-word chapters plus one 20,000-word outlier should still trigger
  consolidation, since the book's *typical* chapter is still too small.
