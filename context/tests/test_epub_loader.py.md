---
source: tests/test_epub_loader.py
last_synced: 2026-09-22T23:30:00Z
source_hash: 7f61d121842defd00eade13fbca2ec311ed050c5
---

## Purpose
Verifies `bookrag.ingest.epub_loader.load_chapters` and `extract_metadata`
against a synthetic 2-chapter epub (built by `tests/helpers.build_sample_epub`,
shared with `test_cli.py`), the heading-split behavior for bundled
(Gutenberg-style) documents, the `text/html`-media-type regression found via
a real commercial epub (Atomic Habits), and the `<head><title>`-leak
regression found via the same book's actual source file.

## Key Decisions
- The synthetic epub's spine is `["nav", c1, c2]` — includes a real `EpubNav`
  document to make sure `load_chapters` correctly excludes nav/TOC content
  from the returned chapters (asserted implicitly: the test expects exactly
  2 chapters, not 3).
- `test_load_chapters_splits_a_single_bundled_document_by_heading` builds one
  spine document containing two `<h2>` headings, mirroring real Gutenberg
  epubs (confirmed against an actual Moby-Dick download: 11 chapters
  before this fix, 147 after — 135 real chapters plus front/back-matter
  noise, see `context/src/bookrag/ingest/epub_loader.py.md`).
- `test_load_chapters_does_not_leak_head_title_into_chapter_text` reuses
  the same `media_type="text/html"` `EpubItem` construction as the test
  above it, this time with a real `<head><title>` present - the exact
  shape of Atomic Habits' actual source file, where this leak was found
  (see that file's context doc for the full root-cause trace).
- **Four tests cover the locator evidence the loader recovers**, all added
  for `bookrag.locate`: a chapter titled from the table of contents when its
  document has no heading (the Ranger's Apprentice / Eye of the World shape,
  worth 1->75 and 0->54 titled chapters); that a document split into several
  chapters does *not* share one TOC label across all of them; that a
  page-scanned epub records `page_N` filenames as page numbers; and that an
  ordinary epub records none, because inventing a page number is worse than
  having none.
