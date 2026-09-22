---
source: src/bookrag/ingest/pdf_loader.py
last_synced: 2026-09-22T21:40:00Z
source_hash: 563a5f6bee0c0945cb0bf28fb080b59faf565c27
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
- `load_chapters_with_sources(path: str | Path) -> list[tuple[None, Chapter]]`
  — the same chapters, in the shape `epub_loader` returns, so `cli._ingest`
  can load either format through one call. The source is always `None`: a PDF
  has no per-chapter source document to name, and `None` is what tells
  `ingest.omnibus` there is nothing here it can read.
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
- **A PDF omnibus cannot be detected, because of the level-1 preference
  above.** `ingest.omnibus` splits a stitched-together epub by reading the
  volume boundaries out of its nested table of contents; in a PDF whose
  outline nests the same way (level 1 = volume, level 2 = chapter) this
  loader flattens to level 1 first, so each *volume* arrives as one
  "chapter" and the nesting is gone before anything can read it. Fixing it
  means keeping the outline's depth and deciding chapter granularity
  afterwards — a change to how every PDF is chaptered, not just omnibuses,
  which is why it was not bundled with the epub split.
