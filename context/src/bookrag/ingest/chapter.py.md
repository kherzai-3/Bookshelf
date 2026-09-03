---
source: src/bookrag/ingest/chapter.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 090b676c1d1a47f08fa7840d936654b75b24d0ee
---

## Purpose
Shared `Chapter` data model, factored out of `epub_loader.py` once
`pdf_loader.py` needed the same shape — both loaders return the same type so
downstream extraction code doesn't need to know which format a book came from.

## Public Interface
- `Chapter(index: int, title: str | None, text: str)` — one chapter's plain
  text plus its position and (if found) heading/bookmark title.
