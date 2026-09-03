---
source: tests/test_pdf_loader.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 70eda8ce0004d4c5b81e9da22734e8dc125baf93
---

## Purpose
Verifies `bookrag.ingest.pdf_loader.load_chapters` and `extract_metadata`
against synthetic PDFs: a 2-chapter one from `tests/helpers.build_sample_pdf`,
plus one built inline with no TOC at all.

## Key Decisions
- Covers both branches of the loader: TOC-based chaptering, and the
  whole-document fallback when a PDF has no outline/bookmarks at all.
