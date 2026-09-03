---
source: src/bookrag/storage.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 4f7fb0d23652d71c98b7a2ffa681268b2d403eb9
---

## Purpose
Persists one ingested book (source file + chapters + metadata) under
`data/library/<book_id>/`, and maintains a series-aware `index.json` for
listing/grouping books without ever merging their chapter numbering.

## Public Interface
- `library_root() -> Path` — `data/library` by default, overridable via the
  `BOOKRAG_LIBRARY_ROOT` env var (used by tests, and by anyone running the CLI
  from outside the project root).
- `incoming_root() -> Path` — `data/incoming` by default, overridable via
  `BOOKRAG_INCOMING_ROOT`. Used by `cli._remove_if_from_incoming` to decide
  whether a successfully-ingested source file is safe to auto-delete (only
  files actually under this root are removed - an arbitrary path elsewhere
  is never touched).
- `slugify(text: str) -> str` — lowercase, hyphenated slug; falls back to
  `"book"` if nothing alphanumeric survives.
- `unique_book_id(title: str, root: Path) -> str` — slug of `title`, with a
  `-2`, `-3`, ... suffix appended until it doesn't collide with an existing
  directory under `root`.
- `save_book(source_path, chapters, *, title, author=None, series_name=None,
  series_position=None, root=None) -> str` — copies the source file, writes
  `metadata.json` and `chapters.jsonl`, updates `index.json`, returns the new
  `book_id`.
- `load_chapters(book_id, root=None) -> list[Chapter]` — reads a book's
  `chapters.jsonl` back into `Chapter` objects (used by extraction/eval).
- `load_index(root=None) -> dict` — the raw `index.json` (`{"books": []}` if
  it doesn't exist yet).
- `series_reading_order(book_id, root=None) -> list[str]` — ordered
  `book_ids` leading up to and including `book_id`: `[book_id]` if
  standalone, otherwise every earlier book in the same series (by
  `series.position`) followed by `book_id`. The one piece of bookkeeping
  both extraction (`extract.pipeline`, seeding known-entities context across
  a series) and spoiler-safe querying (`bookrag.query.facts_as_of`) depend
  on - added when building the extraction layer.

## Key Decisions
- **Series disambiguation**: chapters are addressed as `(book_id,
  chapter_index)`, never a bare chapter number. Two books in the same series
  can each have a "chapter 2" without collision, because each book gets its
  own directory and its own `chapters.jsonl` — `series` on a book's metadata
  is purely a grouping signal for later cross-book work (e.g. a character
  catalog spanning a series), and never merges two books' chapters into one
  numbering space. See `test_series_books_each_keep_their_own_chapter_2` in
  `tests/test_storage.py`.
- `book_id` is derived from the title slug, not from series name/position —
  a book keeps a stable, human-readable id regardless of whether series info
  is supplied or later changes.
- Chapters are stored as JSONL (one `Chapter` per line) rather than a single
  JSON array, so a future streaming/partial read doesn't require parsing the
  whole file.
- `save_book` is all-or-nothing: the file copy, `metadata.json`,
  `chapters.jsonl`, and the `index.json` update are wrapped in a `try`
  whose `except` removes the just-created `book_dir` and re-raises. A
  failure partway through (disk full, permissions, a future bug) leaves no
  partially-written `book_id` directory behind - either `save_book` fully
  succeeds or it's as if it was never called. See
  `test_save_book_leaves_no_partial_directory_on_failure`.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter`

## Data Contracts
- `metadata.json`: `{book_id, title, author, series: {name, position} | null,
  source_format, source_filename, ingested_at, chapter_count}`
- `chapters.jsonl`: one `{index, title, text}` object per line, in the same
  order and shape as the `Chapter` dataclass.
- `index.json`: `{"books": [{book_id, title, author, series}, ...]}` — one
  entry per book, replaced (not appended) on re-ingest of the same `book_id`.

## Open Questions / TODOs
- No de-duplication across ingests of the *same* underlying book (re-running
  `ingest` on the same file creates a second `book_id` via the collision
  suffix, e.g. `the-hobbit-2`) — acceptable for now since there's no
  extraction/query layer yet to make that confusing.
