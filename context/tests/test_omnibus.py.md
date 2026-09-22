---
source: tests/test_omnibus.py
last_synced: 2026-09-22T21:40:00Z
source_hash: 5df548b20d7c55be7108bfba5143ebf398c93db8
---

## Purpose
Covers `ingest.omnibus` and the split it drives at ingest: that a
stitched-together file becomes one book per volume with its own chapter
numbering, and — weighted more heavily — that a book which is *not* an
omnibus is never split.

## Public Interface
23 tests in four groups: detection, volume titles, ingest end-to-end, and
one regression guard that a single book's ingest is unchanged.

## Key Decisions
- **Three separate refusal tests, one per guard, against one happy path.**
  The failure modes are asymmetric: not splitting an omnibus leaves the tool
  as it was, while splitting a novel shatters it silently. Each refusal uses
  a fixture shaped from the real book that trips that specific guard.
- **Each guard is sabotage-verified**, and that caught two tests passing for
  the wrong reason:
  - The coverage test originally gave each section one 700-word chapter,
    putting it under `MIN_VOLUME_WORDS` — so it passed with the coverage
    check deleted. It now asserts both sections clear the size floor before
    asserting coverage is what refused them.
  - The "nested group inside a volume" test originally used the plain
    omnibus fixture, which has no nested group, making it a duplicate of the
    happy path. `build_omnibus_epub(appendix_in_last_volume=...)` was added
    so it actually exercises the depth-0 restriction.
  With the fix in place, disabling any one of overlap / coverage /
  `MIN_VOLUME_WORDS` / depth-0-only fails exactly one test and leaves the
  rest green.
- The load-bearing end-to-end assertion is that each volume's chapter
  indices restart at `[0, 1, 2]` — that is the correctness claim the whole
  feature rests on, not the book count.
- `series_reading_order` is asserted directly rather than through the index,
  because the series metadata is what keeps the split volumes wired together
  for extraction seeding and `facts_as_of`.

## Dependencies
- Internal: `bookrag.cli.main`, `bookrag.ingest.omnibus`,
  `bookrag.ingest.epub_loader`/`pdf_loader`, `bookrag.storage`,
  `tests.helpers` (`build_omnibus_epub`, `build_anchored_sections_epub`,
  `build_thin_sections_epub`, `build_sample_epub`, `build_sample_pdf`)
- External: `pytest`

## Open Questions / TODOs
- No fixture covers a PDF that *would* be an omnibus if the outline depth
  survived `pdf_loader`; `test_a_pdf_is_never_split` only pins the current
  behaviour, not the eventual fix.
