---
source: tests/test_consolidate.py
last_synced: 2026-09-22T23:30:00Z
source_hash: 6219accd6fe458c3aa872636ccfeade27d0cc2c4
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
- `test_consolidate_fragments_merges_across_a_titled_fragment` and
  `test_consolidate_fragments_keeps_first_title_when_several_are_present`
  encode the title-boundary fix: merging is decided **purely on word count**,
  and a fragment having a title is not a reason to stop merging. A real PDF
  whose bookmark "titles" were internal tool-generated ids defeated
  consolidation completely under the old title-respecting rule (146 fragments
  stayed 146); under these rules the same book consolidates to 18 chapters.
- **Two tests pin that merging carries the page span through**, first page
  to last, and that a merge of unpaged fragments keeps `None`. Consolidation
  is where page numbers would otherwise be lost, and the books that need
  merging (160 one-page PDF fragments; 285 scanned epub pages) are exactly
  the ones with no usable chapter titles - so losing the span leaves them
  with no locator at all.
