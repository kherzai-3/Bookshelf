---
source: src/bookrag/ingest/consolidate.py
last_synced: 2026-09-08T00:00:00Z
source_hash: f7b426b46d4db19d8af03d28b8892f68449a77d4
---

## Purpose
Merges many small, incoherent chapter fragments into larger, more coherent
ones before they're persisted - for a book whose loader output is
real-page-sized (or otherwise too small to extract well from
independently) rather than real-chapter-sized. Motivating case: Atomic
Habits, a page-scanned Internet-Archive epub that came out as 286
untitled, ~300-word "chapters" (one per physical page - see
`ingest/epub_loader.py`'s context doc) - a real chapter/Law in that book
spans ~30 of these, currently processed as ~30 *independent* extraction
calls sharing nothing but entity names, risking heavy redundant
re-extraction of the same concepts and losing coherence (an idea
introduced on one page and elaborated on the next is two unrelated calls).

## Public Interface
- `CONSOLIDATION_MEDIAN_WORDS_THRESHOLD = 600` — trigger threshold.
- `CONSOLIDATION_TARGET_WORDS = 2000` — merge target size.
- `should_consolidate(chapters: list[Chapter]) -> bool` — true when the
  *median* fragment word count is below the threshold.
- `consolidate_fragments(chapters: list[Chapter], target_words: int = CONSOLIDATION_TARGET_WORDS) -> list[Chapter]`
  — greedily merges consecutive fragments until reaching `target_words`,
  re-indexing from 0.

## Key Decisions
- **Triggers on fragment *size* (median word count), not on
  `cli.classify_ingestion`'s title-presence signal.** Considered and
  rejected: Ranger's Apprentice is *also* mostly untitled (median chapter
  ~1900 words, most fragments `title=None` for an unrelated reason - see
  `epub_loader.py`'s context doc) but has perfectly reasonable chapter
  sizes - a title-based trigger would risk consolidating a book that
  doesn't need it. `CONSOLIDATION_MEDIAN_WORDS_THRESHOLD = 600` sits
  comfortably below Atomic Habits' real median (313) and above Ranger's
  Apprentice's (~1900).
- **Median, not mean**, for the trigger decision - a handful of outlier
  long/short fragments (front matter, one unusually long chapter)
  shouldn't skew whether the *typical* fragment needs consolidating.
- **`CONSOLIDATION_TARGET_WORDS = 2000`** is the midpoint of the chapter
  sizes that have worked well for extraction so far (~1500-3000 words, see
  `extract/pipeline.py`'s context doc) - a plain constant justified by real
  observed data, matching how `MIN_NARRATIVE_WORDS`/`maxItems` are already
  tuned in this codebase, not a CLI-configurable knob.
- **A fragment's title is never treated as a forced boundary** - merging is
  driven purely by word count. An earlier version *did* force a flush on
  any titled fragment (on the theory that a book mixing titled and
  untitled fragments should never merge across a genuine chapter break);
  this was reverted after it backfired on a real book, Finite and Infinite
  Games (PDF-sourced), whose TOC assigns every single fragment a title,
  but they're meaningless internal bookmark IDs (`FAIG0001`, `FAIG0002`,
  ...), not real chapter headings. Since every fragment had *some* title,
  the old logic force-flushed after each one, silently producing zero
  merging (146 fragments in, 146 "chapters" out) despite
  `should_consolidate` correctly deciding merging was needed. Once
  `should_consolidate` has decided fragments are too small to be coherent
  extraction units, title text isn't a reliable-enough signal to override
  that - a fragment's *first* title (if any) is still preserved on
  whichever merged chapter it ends up in, just no longer treated as a
  boundary.
- **A trailing under-`target_words` remainder is not merged backward into
  the previous chapter.** `extract.pipeline.MIN_NARRATIVE_WORDS` and the
  extraction prompt's own non-narrative self-censoring already provide a
  safety net for a genuinely tiny leftover; a moderately-sized (if
  under-target) final chapter is harmless. Flagged as a real but low-cost
  gap, not silently ignored.
- **Lives here, not in `epub_loader.py` or `extract.pipeline`.** This is a
  format-agnostic concern (a PDF that comes out over-fragmented would need
  the same fix, not an epub-specific one), and doing it once at ingest
  time - before `chapters.jsonl` is written - keeps every downstream
  consumer (`cli.sanity_summary`/`classify_ingestion`/
  `write_ingestion_report`, `extract_book`, `bookrag chat --chapter N`'s
  range check) seeing one consistent chapter count and meaning, rather than
  `chapters.jsonl` showing raw fragments while extraction silently operates
  on a different, unpersisted batch structure.
- **No risk to `chapter_index`-dependent code** (checked directly):
  `storage.series_reading_order` keys purely on `book_id`/`series.position`,
  never chapter count; `query.facts_as_of` only compares `chapter_index`
  within the same book being queried. `chapter_index` was already a
  reassigned-at-ingest-time integer before this (`epub_loader.load_chapters`
  already does `Chapter(index=len(chapters), ...)` over its own
  heading-split output) - this just reassigns it again over a smaller
  merged list, the same kind of transformation that already happens once
  today.

## Data Contracts
- Input/output: `list[Chapter]` (shared dataclass from `ingest.chapter`) -
  a pure transformation, no I/O.

## Dependencies
- Internal: `bookrag.ingest.chapter.Chapter`

## Open Questions / TODOs
- `CONSOLIDATION_TARGET_WORDS`/`CONSOLIDATION_MEDIAN_WORDS_THRESHOLD` were
  chosen from Ranger's Apprentice/Atomic Habits data points, not tuned
  against real consolidated-then-extracted output yet - worth revisiting
  once `bookrag eval` has been run against real consolidated Atomic Habits
  chapters (see `cli.py`'s Open Questions). Finite and Infinite Games (a
  third, PDF-sourced real book, every fragment titled with meaningless
  bookmark IDs) is what actually surfaced and validated the title-boundary
  bug fix above - a second confirmed real-world data point beyond Atomic
  Habits.
- `pdf_loader.py` has the *opposite* problem (returns one giant chapter for
  the whole book when there's no outline, `pdf_loader.py:16-18`) - a real,
  symmetric gap this module doesn't address (it merges, doesn't split).
  Not triggered by any currently-ingested PDF; a future ticket, not
  attempted here.
