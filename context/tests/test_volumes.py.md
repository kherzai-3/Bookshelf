---
source: tests/test_volumes.py
last_synced: 2026-09-22T20:19:13Z
source_hash: b0716042db25476cadff62ca30878d7ff67dc47f
---

## Purpose
Covers `ingest.volumes`: finding the separately published books stitched into
one epub, keeping them as a span map rather than splitting the file, and
carrying that map through consolidation and a real ingest.

## Public Interface
21 tests in four groups — detection, volume titles, surviving consolidation,
and ingest.

## Key Decisions
- **Four refusal tests against one happy path, because the detector's job is
  asymmetric.** Missing an omnibus costs a citation its volume label, which
  is a worse locator. Inventing volumes puts a *wrong book title* on a
  citation, silently. Each refusal uses a fixture shaped from the real book
  that trips that guard, and the guards are isolated deliberately —
  `build_anchored_sections_epub` for overlap, `build_thin_sections_epub` for
  coverage, a one-chapter-per-volume omnibus for the size floor.
- The coverage test re-derives the word counts and asserts the sections
  clear `MIN_VOLUME_WORDS` first. Without that it passed with the coverage
  check deleted — the size floor was doing the work.
- **This file replaced `test_omnibus.py` when the split was removed.** The
  detection tests are unchanged, because the detection is unchanged; what
  moved is everything downstream. Gone with the split: the series-assignment
  tests (a bindup is one book, so nothing assigns a series), the
  shared-source-archive test, and the `--no-split` test.
- **`test_matter_outside_every_volume_is_kept` is the inverse of a test that
  used to assert the opposite.** The split deleted those chapters and
  reported the deletion; on the real Ranger's Apprentice bindup that
  included an 8,500-character extract from book 3. Keeping them costs
  nothing: they are cited by the file's own title.
- **`test_a_page_scanned_omnibus_keeps_its_volume_labels` is a fixture, not
  a measurement, and that is stated.** No book in the corpus is both an
  omnibus and fragment-sized, so nothing real exercises the interaction
  between consolidation and the volume map. The fixture's `chapter_words`
  has to sit below `CONSOLIDATION_MEDIAN_WORDS_THRESHOLD` and multiply up
  past `MIN_VOLUME_WORDS` across a volume; the first attempt used 100 words
  and the volumes fell under the size floor, so detection never fired and
  the test was asserting nothing.
- The same test asserts each volume's merged text contains its own volume's
  fragments **and not the other's**, which is the property `boundaries`
  buys. Asserting only that the labels survived would pass with the
  boundary rule deleted.

## Dependencies
- Internal: `bookrag.ingest.volumes`, `bookrag.ingest.consolidate`,
  `bookrag.ingest.epub_loader`/`pdf_loader`, `bookrag.cli.main`,
  `bookrag.storage.load_chapters`, `tests.helpers`
- External: `pytest`

## Open Questions / TODOs
- Nothing here covers a PDF omnibus, because one cannot be detected — see
  `ingest/pdf_loader.py`'s context doc. The PDF test only pins that the
  detector declines rather than crashes.
