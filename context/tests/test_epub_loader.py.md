---
source: tests/test_epub_loader.py
last_synced: 2026-09-08T00:00:00Z
source_hash: 7037bb278b95484d63c436c21bf8faa12bf05972
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
