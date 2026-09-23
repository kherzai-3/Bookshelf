---
source: tests/test_consolidate.py
last_synced: 2026-09-23T00:00:00Z
source_hash: 9ee5578f6ed62d38ec926992ac1e9d2dced335e4
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

## `split_for_extraction` (added 2026-09-23)

The symmetric half of this module - splitting a chapter *down* for extraction,
where the rest merges fragments *up* at ingest.

- `test_a_normal_chapter_passes_through_split_untouched` — the common case,
  asserted as byte-identical rather than merely "about the same". Six of the
  eight books in the corpus have no chapter near the threshold.
- `test_an_oversized_chapter_is_split_into_pieces` / `test_split_never_cuts_mid_sentence`
  — pieces exist and every line in them is a whole original paragraph.
- `test_split_overlaps_pieces_so_a_boundary_paraphrase_survives` — that the
  tail of one piece really reappears at the head of the next. Overlap is not
  cosmetic: measured on 94 real statements, going from no overlap to 150 words
  at 800-word pieces took lost quotes from 2 to 0.
- `test_split_handles_both_paragraph_separators` — **the most valuable test
  here.** `epub_loader` joins paragraphs with `"\n"` and `consolidate_fragments`
  joins fragments with `"\n\n"`. A splitter that only knows the blank line
  returns one piece for every ordinary epub chapter, which looks like a clean
  pass and silently does nothing. The first version of the measurement harness
  had exactly this bug and reported a flawless zero-impact result that was
  entirely an artifact of never having split anything.
- `test_an_unbroken_wall_of_text_is_not_split` — no paragraph boundary means no
  cut that isn't mid-sentence, and that is worse than a large prompt.
- `test_split_threshold_sits_above_the_consolidation_target` — pins the
  relationship between the two halves, so a chapter just merged up to
  `CONSOLIDATION_TARGET_WORDS` is never immediately taken apart again. A
  regression here would have the two functions fighting each other.

### The default-off switch (added 2026-09-23)

- `test_splitting_is_off_by_default_whatever_the_chapter_size` — pins
  `SPLIT_OVERSIZED_CHAPTERS is False` *and* that a 20,000-word chapter still
  comes back whole through the default path, while the mechanism still works
  when a threshold is passed explicitly. Both halves matter: the first stops
  the switch being flipped by accident (it would change 48 of one real book's
  108 chapters), the second stops the tests below from silently becoming
  no-ops if it ever is.
- Every other splitting test now passes `threshold_words=3500` explicitly.
  That is deliberate rather than incidental — with the switch off, a test
  relying on the default would pass while asserting nothing, which is exactly
  the failure the `"\n\n"` separator bug already produced once in the
  measurement harness.
