---
source: tests/test_epub_loader.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 7f1a970534b654cb5ba638bf31dd2b0dc4553129
---

## Purpose
Verifies `bookrag.ingest.epub_loader.load_chapters` and `extract_metadata`
against a synthetic 2-chapter epub (built by `tests/helpers.build_sample_epub`,
shared with `test_cli.py`), the heading-split behavior for bundled
(Gutenberg-style) documents, and the `text/html`-media-type regression
found via a real commercial epub (Atomic Habits).

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
