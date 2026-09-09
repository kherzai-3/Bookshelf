---
source: src/bookrag/storage.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 4f92efc240add5df9b03e33b2d80301c488d59ab
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
  series_position=None, content_type="fiction", root=None) -> str` —
  copies the source file, writes `metadata.json` and `chapters.jsonl`,
  updates `index.json`, returns the new `book_id`. `content_type` (added
  for non-fiction support) is just persisted here - `save_book` itself
  doesn't interpret it, only stores it for `extract.pipeline`/`eval.py`/
  `cli._chat` to pick up later via `load_metadata`.
- `load_chapters(book_id, root=None) -> list[Chapter]` — reads a book's
  `chapters.jsonl` back into `Chapter` objects (used by extraction/eval).
- `load_metadata(book_id, root=None) -> dict` — reads a book's
  `metadata.json` back. Added alongside `content_type` - nothing read
  `metadata.json` back before this (only wrote it); every consumer of
  `content_type` uses `.get("content_type", "fiction")` rather than direct
  indexing, since a book ingested before this field existed has no such
  key.
- `load_index(root=None) -> dict` — the raw `index.json` (`{"books": []}` if
  it doesn't exist yet).
- `remove_from_index(book_id, root=None) -> bool` — removes `book_id`'s
  entry from `index.json` if present; returns whether an entry was actually
  found and removed. The inverse of `_update_index`'s upsert, made public
  (unlike `_update_index`) since `library.remove_book`/`bookrag doctor`
  are legitimate external callers, not just `save_book` internals. Works
  even when the entry is already orphaned (directory gone) - it only
  touches `index.json`.
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
  content_type: "fiction" | "nonfiction", source_format, source_filename,
  ingested_at, chapter_count}`. `content_type` selects which extraction
  category/entity-type taxonomy and prompt pair a book uses (see
  `providers/prompts.py`/`providers/parsing.py`) - a book saved before this
  field existed simply has no key; every reader defaults it to `"fiction"`.
- `chapters.jsonl`: one `{index, title, text}` object per line, in the same
  order and shape as the `Chapter` dataclass.
- `index.json`: `{"books": [{book_id, title, author, series}, ...]}` — one
  entry per book, replaced (not appended) on re-ingest of the same `book_id`.

## Open Questions / TODOs
- No de-duplication across ingests of the *same* underlying book (re-running
  `ingest` on the same file creates a second `book_id` via the collision
  suffix, e.g. `the-hobbit-2`). Originally deprioritized on the reasoning
  that there was no extraction/query layer yet to make a duplicate
  confusing - both now exist (`extract_book`, `bookrag chat`), and a real
  extraction run takes on the order of 2+ hours (see `ollama_provider.py`'s
  context doc), so an accidental duplicate silently wasting a full run
  against the wrong copy is a real cost now, not a hypothetical one. Worth
  revisiting.
