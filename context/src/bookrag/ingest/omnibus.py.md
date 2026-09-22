---
source: src/bookrag/ingest/omnibus.py
last_synced: 2026-09-22T21:40:00Z
source_hash: 6407e6a00617288ad2cd61c671692f4754bf6bc0
---

## Purpose
Finds the separately-published books stitched together inside one file (a
bindup, a "complete collection", a fan-compiled series epub) and says where
each one starts and ends, so `cli._ingest` can write them as separate books
instead of one long one. Whole, an omnibus produces a book with five
"Chapter 1"s and chapter numbers no reader can find in their own copy:
`--chapter 40` means nothing to someone on chapter 6 of book 3, and "up to
chapter 40" spans two books, so spoiler scoping is coarser than it looks.

## Public Interface
- `Volume` — one book inside the file: `title`, `label` (the TOC heading
  verbatim), `start`/`end` (inclusive chapter indices), `words`.
- `OmnibusPlan` — `volumes`, `chapter_count`, `total_words`, `covered_words`,
  plus `coverage`, `dropped_chapters`, `dropped_words` properties.
- `detect_volumes(path, chapters, chapter_sources, book_title) -> OmnibusPlan | None`
  — `None` for the usual case, one book.
- `volume_chapters(chapters, volume) -> list[Chapter]` — one volume's
  chapters, re-indexed from 0.
- `MIN_VOLUMES`, `MIN_VOLUME_WORDS`, `MIN_TEXT_COVERAGE` — the three guards.

## Key Decisions
- **The signal is the file's own nested table of contents.** Every omnibus in
  the corpus nests one TOC section per book, and the section's spine items
  give the span directly. No heuristic over the prose (a repeated title
  pattern, a chapter numbering that restarts) is used or needed — and neither
  would have worked: Reverend Insanity's 24 volumes number chapters 1–2334
  straight through, and Magic Thief's volume titles share a prefix rather
  than repeating.
- **Finding the nesting is easy; refusing the nesting that isn't a book is
  the work.** Splitting a novel that is not an omnibus is far worse than
  leaving an omnibus whole: it is silent, and a reader has no reason to
  suspect it. Three guards, measured on the real library:

  | book | volumes | overlap | coverage | smallest volume |
  | --- | --- | --- | --- | --- |
  | Ranger's Apprentice bindup | 2 | no | 98.4% | 64,897 w |
  | The Magic Thief collection | 5 | no | 99.9% | 7,405 w |
  | Reverend Insanity | 24 | no | 100.0% | 73,051 w |
  | Moby Dick (Gutenberg) | 5 | **yes** | **45.2%** | — |

  Moby Dick is the case the guards exist for. Its five nested sections
  ("ETYMOLOGY.", "CHAPTER 100. Leg and Arm.", "Epilogue", …) are anchors
  inside single spine documents, so their spans collide — and separately,
  they hold under half the text. It is rejected twice over. The Eye of the
  World, The Perfect Run and Atomic Habits have no nested sections at all
  and never reach the guards.
- **`MIN_VOLUME_WORDS = 1000` is set by a real volume, not a guess.** "The
  Magic Thief: A Proper Wizard" is a published novella of 7,405 words sitting
  between three full novels, so the floor has to stay well under that while
  still rejecting a section that is only a dedication page or a map.
- **`MIN_TEXT_COVERAGE` doubles as a bound on deletion.** Everything outside
  a volume is dropped, so requiring 85% coverage is also the promise that a
  split never discards much. It subsumes a separate gap rule: Magic Thief has
  two interstitial 14-word pages between volumes, and they simply fall inside
  the 0.1% the coverage check already tolerates.
- **Only depth-0 TOC groups are considered volumes.** Magic Thief book 5
  nests "A Guide to People and Places" *inside* its own section; a recursive
  scan would report six books in a five-book collection, and because that
  appendix sits within book 5's span it would then trip the overlap check and
  refuse to split the file at all.
- **An ordinal prefix is stripped from a volume's title, and nothing else
  is.** "Book 1: The Ruins of Gorlan" → "The Ruins of Gorlan". The regex
  requires a number (or roman/spelled-out equivalent) after the keyword, so
  "Book of the New Sun" keeps its first word. When stripping leaves nothing
  ("Volume 7", all 24 of Reverend Insanity's), the file's own title qualifies
  it — a library holding a book called "Volume 7" tells a reader nothing.
- **epub only, and that is a gap rather than a decision.** `pdf_loader`
  flattens a PDF outline to level-1 entries, so a nested PDF arrives here as
  one "chapter" per volume with the nesting already gone. `chapter_sources`
  is all `None` for a PDF, which is what signals it.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter`
- External: `ebooklib` (reads the TOC)

## Data Contracts
- In: the loaded `chapters`, and `chapter_sources[i]` = the spine document
  chapter `i` came from (from `epub_loader.load_chapters_with_sources`). The
  pairing cannot be reconstructed afterwards — `_split_by_headings` turns one
  spine document into several chapters for some books and drops empty ones
  for all of them, so chapter index and spine position do not line up.
- Out: `OmnibusPlan | None`. Spans are inclusive chapter indices into the
  list passed in, sorted, disjoint. Chapters in no span are front/back matter
  and are dropped by the caller.

## Open Questions / TODOs
- PDF omnibuses are not detected. Fixing it means teaching `pdf_loader` to
  keep the outline's depth, which changes how every PDF is chaptered, not
  just omnibuses.
- An epub whose volumes are not marked in its table of contents (books
  concatenated by hand; a TOC listing every chapter flat) has no signal here
  and is left whole. No prose-level fallback is built, on purpose — see the
  false-positive asymmetry above.
- The series name a split produces is the omnibus's own title, which is often
  clunky ("Ranger's Apprentice 1 & 2 Bindup"). Deriving a better one from the
  volume titles' common prefix would work for Magic Thief and not for
  Ranger's Apprentice; `--series` is the honest override.
