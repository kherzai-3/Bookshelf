---
source: src/bookrag/ingest/epub_loader.py
last_synced: 2026-09-02T00:00:00Z
source_hash: 9b76b68020c47eaaec31e3184f06f2c294c9125c
---

## Purpose
First real ingestion component. Reads an `.epub` file and returns its chapters
as plain text, in reading order, so downstream extraction (characters,
settings, themes) can be scoped per chapter for spoiler-safety.

## Public Interface
- `load_chapters(path: str | Path) -> list[Chapter]` — parses the epub's spine
  in order, strips HTML, and returns one `Chapter` per non-empty content
  document (nav/TOC documents are skipped).
- `extract_metadata(path: str | Path) -> dict[str, str | None]` — best-effort
  `{"title", "author"}` from the epub's Dublin Core metadata.

## Key Decisions
- Chapter order comes from `book.spine`, not `book.toc` or file name sorting —
  the spine is the epub's authoritative reading order and can differ from
  either.
- **Content documents are identified by `item.media_type` (checked against
  `{"application/xhtml+xml", "text/html"}`), not `item.get_type()`.** Found
  via a real commercially-produced epub (Atomic Habits) that declares
  `text/html` instead of the spec-required `application/xhtml+xml`:
  ebooklib only upgrades an item to `EpubHtml` (whose `get_type()` always
  reports `ITEM_DOCUMENT`) for the spec media type, so a `text/html` item
  stays a plain `EpubItem`, whose `get_type()` guesses from the file
  extension and doesn't recognize `.html` at all - `load_chapters` silently
  returned zero chapters for the entire book before this fix. See
  `tests/test_epub_loader.py::test_load_chapters_handles_text_html_media_type`.
- **Real-world validation with Project Gutenberg's Moby-Dick epub found the
  spine alone is not enough**: Gutenberg bundles ~10-13 real chapters per
  spine file, with actual breaks marked only by an internal `h1/h2/h3`
  heading. `load_chapters` now runs each spine document through
  `_split_by_headings`, which splits on heading boundaries when a document
  has more than one heading, and leaves it whole (prior behavior) when it
  has 0 or 1 — this fixed an 11-vs-135-chapter undercount without changing
  behavior for well-structured epubs (one chapter per file, one heading each).
- This does surface front/back-matter (title page, license text) as a
  handful of extra low-value pseudo-chapters when *those* sections also carry
  heading tags — deliberately not filtered out (see `cli.sanity_summary`,
  which is the intended way to catch this per-book rather than a fragile
  "is this really a chapter" classifier).
- Title extraction is a best-effort scan for the first `h1`/`h2`/`h3` in the
  chapter's HTML; many epubs have no heading markup, so `title` is `None` in
  that case rather than guessed from content.
- HTML-to-text uses `lxml.html` (`text_content()`) rather than adding
  `beautifulsoup4` as a dependency, since `lxml` is already pulled in
  transitively by `ebooklib`.
- `_split_by_headings` marks split points by inserting a sentinel `<span>`
  before each heading, then splitting the document's full `text_content()`
  on that sentinel string. The sentinel is wrapped in a Private Use Area
  Unicode character so it can't collide with real book text (a literal NUL
  byte, the more obvious choice, is rejected by lxml as invalid XML text).

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter` (shared with `pdf_loader.py`)
- External: `ebooklib` (epub parsing), `lxml` (HTML-to-text)

## Data Contracts
- Output: `list[Chapter]`, one per spine content document that has non-empty
  text after HTML stripping. `index` is contiguous starting at 0 over the
  *kept* chapters (skipped/empty documents don't consume an index).

## Open Questions / TODOs
- Some real-world text has garbled characters after extraction (observed:
  em-dash became `�` in a chapter title) - likely an encoding edge case in
  `text_content()` or the source file itself; not yet investigated.
- **Some epubs have no exploitable structural signal at all** (observed:
  Atomic Habits - no heading markup in any content document AND an empty
  nav TOC, `<ol/>` with zero entries). `load_chapters` then returns one
  "chapter" per spine file, which may be an arbitrary page-sized fragment
  bearing no relation to real chapters (286 untitled fragments for a book
  with ~20 real chapters). No further heuristic was attempted - with zero
  signal, any chapter-merging guess would be fabricated, not extracted.
  Left as a documented limitation (README) for the sanity summary to
  surface, same posture as other unfixable-without-more-signal cases.
- Chapter titles from `book.toc` (nav labels) aren't cross-referenced yet;
  could improve title recall for epubs whose content lacks heading tags.
