---
source: tests/test_pdf_loader.py
last_synced: 2026-09-22T23:30:00Z
source_hash: acc887bcd85cb523f5c65b7f4dd3ef11f3163953
---

## Purpose
Verifies `bookrag.ingest.pdf_loader.load_chapters` and `extract_metadata`
against synthetic PDFs: a 2-chapter one from `tests/helpers.build_sample_pdf`,
plus one built inline with no TOC at all.

## Key Decisions
- Covers both branches of the loader: TOC-based chaptering, and the
  whole-document fallback when a PDF has no outline/bookmarks at all.
- **Chapter page ranges are asserted 1-indexed**, matching both the PDF
  outline's own numbers and what a PDF reader shows - a citation whose number
  disagrees with the page box the reader types into is useless. This is the
  only locator available for a PDF whose outline entries are meaningless
  bookmark IDs, the real *Finite and Infinite Games* case.
