---
source: src/bookrag/titles.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 8e08861ac83a772bd73682cb584ba9094fb5fffc
---

## Purpose
Best-effort title/author guessing from a filename - the last-resort fallback
in `cli.py` when a book has no usable internal metadata (common for scanned
or exported PDFs) and no explicit `--title`/`--author` flag was given.

## Public Interface
- `guess_title_author(filename_stem: str) -> tuple[str, str | None]` — turns
  separators into spaces, splits on a `"... by ..."` pattern into
  (title, author) if present, and title-cases the result (keeping small
  glue words like "of"/"the" lowercase except as the first word).

## Key Decisions
- Only handles the `"<title> by <author>"` filename convention explicitly;
  anything else becomes a single title-cased title with `author=None` rather
  than trying more speculative parsing (e.g. no attempt to strip trailing
  edition/year/id numbers like `pg2701`) — real-world validation: this is
  exactly the case found in `Finite-and-Infinite-Games-by-James-Carse.pdf`,
  which has no internal PDF metadata at all.
- This is deliberately a last resort, below both explicit flags and each
  loader's `extract_metadata` - see `cli.py`'s fallback order.

## Dependencies
- None beyond stdlib (`re`).
