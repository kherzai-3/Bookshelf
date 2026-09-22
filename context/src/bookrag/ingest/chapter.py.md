---
source: src/bookrag/ingest/chapter.py
last_synced: 2026-09-22T23:30:00Z
source_hash: e303e00ad5f7cf57aa38c2b2774e5a3dc6f86fbf
---

## Purpose
Shared `Chapter` data model, factored out of `epub_loader.py` once
`pdf_loader.py` needed the same shape — both loaders return the same type so
downstream extraction code doesn't need to know which format a book came from.

## Public Interface
- `Chapter(index: int, title: str | None, text: str, pages: list[int] | None = None)`
  — one chapter's plain text plus its position, its (if found)
  heading/bookmark title, and the source's own page numbers for it.

## Key Decisions
- **`pages` is `[first, last]` inclusive, and a list rather than a tuple.**
  It round-trips through `chapters.jsonl`: `asdict` writes a tuple as a JSON
  array and `Chapter(**json.loads(line))` reads it back as a list, so storing
  a tuple would make the same chapter compare unequal to itself across a
  save/load cycle. Pinned by
  `tests/test_locate.py::test_pages_survive_a_save_and_load_cycle`.
- **`None` is the honest common case.** An ordinary epub has no pagination at
  all, and inventing a number would be worse than having none. Only two
  shapes populate it: a PDF outline, which gives page numbers directly, and a
  page-scanned epub, which encodes them in its spine filenames
  (`page_200.html`).
- Read by `bookrag.locate` to tell a reader where a fact came from. Nothing
  else depends on it, and every chapter written before the field existed
  simply has no key.
