---
source: src/bookrag/ingest/consolidate.py
last_synced: 2026-09-23T00:00:00Z
source_hash: e7ab772eeb1452c113b0565b92d986daa02312e8
---

## Purpose
Gets a book's text into units an extraction call can actually handle, from
either direction - merging *up* when fragments are too small, splitting *down*
when a chapter is too big.

**The two halves run at different times, and that is the important thing about
this module.** `consolidate_fragments` runs at **ingest**, because it changes
what a chapter *is* - for the reader, for citations, for `chat --chapter N`.
`split_for_extraction` runs at **extract** time and changes nothing that is
stored; see its section below.

### Merging up (`consolidate_fragments`)
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
- `consolidate_fragments(chapters, target_words=CONSOLIDATION_TARGET_WORDS, boundaries=frozenset()) -> list[Chapter]`
  — greedily merges consecutive fragments until reaching `target_words`,
  re-indexing from 0.
- `fragment_groups(chapters, target_words=..., boundaries=...) -> list[list[int]]`
  — the same grouping decision, as input indices rather than merged
  chapters.
- `SPLIT_OVERSIZED_CHAPTERS = False` — **the master switch, and it is off.**
- `SPLIT_THRESHOLD_WORDS = 3500` — above this, a chapter is split for
  extraction, once the switch is on.
- `SPLIT_TARGET_WORDS = 1800` — target size of each piece.
- `SPLIT_OVERLAP_WORDS = 150` — text repeated across a boundary.
- `split_for_extraction(text, target_words=..., overlap_words=..., threshold_words=...) -> list[str]`
  — `text` in pieces, or `[text]` unchanged.

## Splitting down (`split_for_extraction`)

**It is OFF, by `SPLIT_OVERSIZED_CHAPTERS = False`, and that is a measured
decision rather than caution.** The mechanism works and is tested; what does
not exist is a decision rule for when to use it. Six oversized chapters of The
Eye of the World, whole vs split, same model and prompt:

| ch | words | coverage | entities | near-dups | time |
|---|---|---|---|---|---|
| 104 | 3,945 | 24→42% | 13→16 | 0→**37** | 2.21x |
| 20 | 4,078 | 38→66% | 15→20 | 2→2 | 1.03x |
| 32 | 4,308 | 46→50% | 23→**13** | 5→**22** | 1.08x |
| 62 | 4,563 | **28→24%** | 5→5 | 113→147 | 0.86x |
| 54 | 4,959 | 50→73% | 7→14 | 6→**2** | 0.93x |
| 42 | 5,172 | 30→69% | 14→**7** | 122→**21** | 0.72x |
| mean | | **+18 pts** | **−0.3** | **−2.8** | 1.14x |

Citation coverage improves in 5 of 6 and is the only near-consistent signal;
entities and near-duplicates average to roughly nothing while swinging hard
both ways. **A rule was proposed from the first five and the sixth killed it:**
"split when the whole chapter saturates the `maxItems` ceiling" is strongly
supported by ch42 and ch54, and ch62 saturated too and is the one chapter where
splitting *cost* coverage, with groundedness falling 0.921→0.647. Word count
does not separate the wins either (best at 4,959 and 5,172, worst at 4,563).

Turning it on would change 48 of that book's 108 chapters on 5-for-6 evidence.
`threshold_words=None` (what `extract_book` passes) honours the switch; passing
an explicit threshold opts in regardless, which is how the tests and a
measurement harness exercise it without flipping a global.

**It never changes what a chapter is.** The caller
(`extract.pipeline.extract_book`) makes one provider call per piece and records
every resulting fact against the chapter's own index. `chapter_index` still
means exactly what it always did, which is what leaves `query.facts_as_of`'s
spoiler filtering, `locate.cite`'s citations, `locate.volume_at`'s spans,
`extraction_progress.json`'s resume granularity and `chat --chapter N` all
completely untouched - and why no book needs re-ingesting. Splitting at ingest
instead would change every one of them.

- **Splitting does not cost time the way it looks like it should, and the
  reason matters.** Per *fact produced*, splitting is consistently faster:
  10.9 / 11.8 / 9.9 seconds per fact against 14.4 / 20.2 / 21.3 whole, on the
  same three chapters. Wall-clock rises only because it produces more facts
  (each piece gets its own `maxItems` budget), and the time ratio tracks the
  fact ratio almost exactly (4.76x facts -> 2.21x time) with no relationship to
  prompt size. Two things make prompt size nearly irrelevant here: decode runs
  ~7x more expensively per token than prefill, and Ollama caches the shared
  prefix, so a chapter's pieces re-send an identical system prompt and entity
  preamble almost free. **`num_ctx` is a memory lever, not a speed lever** -
  worth having for KV cache and GPU fit, worth nothing for wall-clock.
- **`SPLIT_THRESHOLD_WORDS = 3500` was set from the corpus, not picked.**
  Measured across all eight books here, only The Eye of the World (48 of its
  108 chapters, up to 10,509 words) and a handful of outliers elsewhere exceed
  it - Ranger's Apprentice splits exactly 1 chapter of 75. So six of eight
  books are untouched, and the ones that aren't are precisely the ones whose
  chapters were being truncated by the schema's 40-fact ceiling.
- **It sits above `CONSOLIDATION_TARGET_WORDS` (2000) on purpose**, so a
  chapter this module has just merged *up* to target is never immediately taken
  apart again. `tests/test_consolidate.py` pins that relationship.
- **Paragraphs are found with `splitlines()`, not by splitting on a blank
  line.** The two sources disagree: `epub_loader` emits newline-joined
  paragraphs while `consolidate_fragments` joins its fragments with `"\n\n"`.
  Splitting on `"\n\n"` alone yields exactly one piece for every ordinary epub
  chapter - it looks like a clean result and measures nothing. This is not
  hypothetical; the first version of the measurement harness did it and
  reported a flawless zero-impact result that was entirely an artifact.
- **Overlap protects citations and manufactures duplicates. It is a genuine
  trade, not a free win, and the second half was not anticipated.** The
  citation half is measured: taking 94 statements a real model produced and
  asking whether `locate.find_passage` still finds the same quote when it can
  only see one piece, going from no overlap to 150 words at 800-word pieces
  took quotes lost outright from 2 to 0. A paraphrase routinely draws on
  sentences either side of a boundary, and without overlap neither piece holds
  the whole of it.

  But the model *reads the overlapped text twice and reports it twice*, in
  different words each time - which the pipeline's exact-match dedup
  structurally cannot catch. Measured on three oversized real chapters, near-
  duplicate statement pairs went 2->2, 5->22 and 0->37 when splitting. The same
  three chapters improved citation coverage every time (38->66%, 33->50%,
  24->42%) and groundedness every time. So the two effects are coupled by
  construction: the overlap buying the coverage is the same overlap paying in
  duplicates.

  If this is to ship widely, the fix is to extend the pipeline's per-chapter
  dedup from exact-match to near-match **for split chapters only** -
  `eval.near_duplicate_pairs` already implements the similarity test. Not done
  yet; the threshold and the rollout are still gated on more measurement.
- **Overlap carries whole paragraphs, never a partial one** - half a paragraph
  reintroduces the split-evidence problem it exists to solve.
- **A chapter at or under the threshold is returned byte-identical**, so the
  overwhelmingly common case is provably unaffected rather than merely
  believed to be.
- **An unbroken wall of text is not split at all.** With no paragraph boundary
  there is no cut that isn't mid-sentence, and a mid-sentence cut is worse than
  a prompt that is merely large.
- **The final piece is dropped if it holds only the carried-over overlap**
  (`count > overlap_words`), or it would re-send text the previous piece
  already covered with nothing new in it.

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
- **`boundaries` is a hard flush, and only `ingest.volumes` passes any.**
  A bindup's volume seams: merging the last page of one book onto the first
  page of the next produces a chapter that belongs to two books at once, and
  a citation would name whichever won. This is the one signal allowed to
  override word count, and it is allowed because it is structural rather
  than inferred from title text - the distinction the title-boundary bug
  above turned on. No book in the corpus is both an omnibus and
  fragment-sized, so no current data exercises it; a page-scanned bindup is
  an ordinary thing to own.
- **`fragment_groups` is split out and returns indices, not chapters.**
  `ingest.volumes.remap` holds spans over the *input* chapters and has to
  move them onto the output, which needs to know which inputs became which
  merged chapter. Indices rather than `Chapter` objects because a
  `Chapter.index` is set by whoever built it and is not guaranteed to be its
  position in the list handed here.
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

- **Merging carries the page span through, first page to last.**
  Consolidation is both where page numbers earn their keep and where they
  would otherwise be lost: the books that need merging are the page-sized
  ones, so the real cases are 160 one-page PDF fragments becoming 18 chapters
  and 285 scanned epub pages becoming 36. Those two books have no usable
  chapter titles either, so dropping the numbers here would leave them with
  no locator at all. A merged chapter with no paged fragments keeps `None`.

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
- The symmetric gap this doc used to list as future work - "it merges, doesn't
  split" - is now `split_for_extraction`. It does **not** close the
  `pdf_loader.py:16-18` case it was written about, though: a whole book
  returned as one chapter would be split into extraction pieces but would
  still be *stored* as a single chapter, so its citations stay useless and
  `chat --chapter N` still has one value to choose from. That remains a loader
  problem, not a chunking one.
- `SPLIT_TARGET_WORDS`/`SPLIT_OVERLAP_WORDS` are set from a citation-matcher
  measurement (does the same statement still resolve to the same quote) rather
  than from extraction output. That is the cheaper half of the question. The
  harder half - whether the model *writes different statements* when it sees a
  piece instead of a chapter - is what `bookrag eval` and the A/B in the
  project plan measure.
