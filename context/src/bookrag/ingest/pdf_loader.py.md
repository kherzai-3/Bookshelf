---
source: src/bookrag/ingest/pdf_loader.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 683c48b250e765d79632025738a54b6ab0347d38
---

## Purpose
PDF counterpart to `epub_loader.py`. Reads a `.pdf` file and returns its
chapters as plain text, in reading order, using the same `Chapter` shape so
downstream extraction is format-agnostic.

## Public Interface
- `load_chapters(path: str | Path) -> list[Chapter]` — chapters the PDF's
  outline/TOC (bookmarks), one `Chapter` per top-level entry with non-empty
  text; falls back to the whole document as a single chapter if the PDF has
  no TOC at all.
- `extract_metadata(path: str | Path) -> dict[str, str | None]` — best-effort
  `{"title", "author"}` from the PDF's document info dict; blank strings
  (pymupdf's default when unset) are normalized to `None`.

## Key Decisions
- Unlike epub (which has an authoritative spine), a PDF has no structural
  notion of "chapter" — the outline/TOC (`doc.get_toc()`) is the only
  reasonably reliable signal, and even that is opt-in per PDF. Prefer
  level-1 TOC entries (chapters) over deeper ones (sections) to avoid
  fragmenting a chapter into many tiny pieces; if a PDF's TOC has no
  level-1 entries at all, fall back to using every entry it does have.
- No TOC at all (common for scanned/plain PDFs) → the whole document becomes
  one `Chapter` with `title=None`, rather than raising or returning nothing —
  callers still get usable text, just without chapter boundaries.
- Chapter boundaries are page ranges between one entry's start page and the
  next's (or end of document for the last entry); text within a chapter is
  the concatenation of `page.get_text()` over that page range.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter` (shared with `epub_loader.py`)
- External: `pymupdf`

## Data Contracts
- Output: `list[Chapter]`, same contract as `epub_loader.load_chapters` —
  contiguous `index` starting at 0 over the kept chapters.

## Open Questions / TODOs
- No spoiler-safety-relevant metadata is extracted from PDFs beyond text
  (e.g. no page-image/figure handling) — plain text only, same as epub.
