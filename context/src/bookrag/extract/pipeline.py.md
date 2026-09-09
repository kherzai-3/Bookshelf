---
source: src/bookrag/extract/pipeline.py
last_synced: 2026-09-09T00:00:00Z
source_hash: f28240f1b8f62f231e3b5b9f098431c1be51ff50
---

## Purpose
The actual extraction pipeline: runs a `Provider` over every chapter of a
book, in order, resolving entities and writing `facts.jsonl` - the one
place `ExtractedFact`s (raw, provider-shaped) become `Fact` records (stored,
entity-resolved, chapter-scoped).

## Public Interface
- `ExtractionResult(book_id, chapter_count, fact_count, new_entity_count,
  parse_failure_count, ungrounded_entity_count, skipped_chapter_count,
  duplicate_fact_count=0, resumed_from_chapter=None, already_complete=False)`
  — `resumed_from_chapter`/`already_complete` are for resumable extraction
  (see Key Decisions): `resumed_from_chapter` is the chapter index this
  call started at (`None` for a from-scratch run), `already_complete`
  means this call did nothing because a prior run already reached the end.
  `duplicate_fact_count` is how many raw facts this call dropped for being
  an exact repeat of an earlier fact in the same chapter (see Key
  Decisions) - `cli.py` surfaces it like the other counts here when
  nonzero.
- `extract_book(book_id, provider, root=None, on_chapter_done=None,
  restart=False) -> ExtractionResult` — appends to (or, for a from-scratch
  run, overwrites) `data/library/<book_id>/facts.jsonl` and updates
  `data/library/entities.json`. `on_chapter_done`, if given, is called as
  `on_chapter_done(position, total)` after every chapter actually processed
  this call (1-indexed by absolute chapter position in the book, including
  skipped/failed ones - on a resumed run this correctly starts above 1, not
  restarting the count) - `cli.py` uses this to print progress with an ETA,
  but `pipeline.py` itself does no printing. Looks up the book's
  `content_type` via `storage.load_metadata(book_id, root).get(
  "content_type", "fiction")` once at the top and passes it to every
  `provider.extract_facts` call - not a per-chapter lookup, since a single
  book's content type doesn't change chapter to chapter. `restart=True`
  ignores any saved progress/facts and starts over from chapter 0.
- `resume_start_index(book_id, root=None, *, restart=False,
  chapter_count=None) -> int` — read-only, cheap (no `facts.jsonl`/
  `entities.json` access): the chapter index a call to `extract_book` would
  start at right now. Factored out of `extract_book` so `cli.py` can preview
  it *before* running anything, e.g. to print "Resuming from chapter N"
  before the run actually starts rather than only in the final summary.
  Pass `chapter_count` if the caller already has it (avoids a redundant
  `load_chapters` call); otherwise it loads the chapters itself.
- `OnChapterDone = Callable[[int, int], None]` — the callback type alias.
- `MIN_NARRATIVE_WORDS = 20` — a chapter whose text is shorter than this is
  skipped without ever calling the provider (see Key Decisions).

Note: `facts_path` (the open `chapters.jsonl` handle, actually `facts.jsonl`)
is explicitly `.flush()`ed after every chapter, before `on_chapter_done`
fires. This matters when the process's stdout/output is redirected to a
file rather than a real terminal (e.g. a backgrounded run) - Python fully
buffers writes in that case, so without an explicit flush, a real,
in-progress multi-minute extraction looked indistinguishable from a hung
process when checked externally (`facts.jsonl` showed 0 lines for the
first ~20 minutes of a real 75-chapter run that was, per later diagnosis,
almost certainly progressing normally). Diagnosed by testing chapter 0 in
isolation (7.9s, not a hang) after the file appeared frozen.

## Key Decisions
- **Exact-duplicate facts within one chapter's raw response are dropped in
  code, before grounding/resolution** - not relied on the extraction
  prompt's own "don't repeat yourself" instruction to prevent (see
  `prompts.py`'s context doc for that instruction and why it alone wasn't
  reliable). Real observed case: after `providers/parsing.py`'s `maxItems`
  was raised from 25 to 40 to stop cutting off real late-chapter content,
  a real chapter's real extraction padded toward the new cap by repeating
  the exact same status sentence 20+ times rather than stopping once
  genuinely distinct content ran out. Matching is on `(entity_name,
  statement)` case-insensitively - an exact repeat only, never a
  near-duplicate rephrasing (which could legitimately be two separate
  observations of the same fact). Counted in `duplicate_fact_count`,
  surfaced by `cli.py` like the other counts here, not silently dropped.
- Chapters are processed **sequentially, never in parallel** - each
  chapter's `known_entities` list grows as facts are resolved, so chapter 5
  sees entities introduced in chapters 0-4. Parallelizing would break this
  incremental context (and, for the real Claude provider, chapters would
  race to append to the same `entities` dict).
- `known_entities` is seeded before the first chapter processed **this
  call** from `series_reading_order(book_id)` **including `book_id`
  itself** (changed from excluding it) - this is both what lets book 2 of a
  series not re-introduce a character book 1 already established, *and*
  what makes resuming correct: a resumed call needs to know about every
  entity *this same book* already resolved in its own earlier (pre-
  interruption) chapters, or the grounding check below would wrongly treat
  an already-established entity as brand new the moment a run resumes. On a
  genuinely fresh run this is a no-op (`book_id` has no entities yet), so
  the change is safe for the non-resume case too.
- **`known_types` (built by `_entity_types_for_books`, same book-id scope
  as `known_names`) is threaded through to the provider alongside the bare
  name list**, and updated inline (`known_types[raw.entity_name] =
  raw.entity_type`) the same moment a new entity is added to `known_names`.
  Passed as `known_entity_types` to `provider.extract_facts` (see
  `providers/base.py`/`prompts.py`) purely as a prompt-building hint - the
  grounding/resolution logic below (`is_new`, `resolve_entity`) is
  untouched by this and still only ever sees the plain name list. Added
  after confirming (real data) that a recurring entity's type can drift
  across chapters - `known_names` alone gives the provider zero signal
  about what type a name was already recorded as, so it re-derives one
  from scratch each time. If the same name was inconsistently typed in
  entities already on record before this existed, `_entity_types_for_books`
  just picks whichever type it iterates over last - an acceptable,
  harmless arbitrary tie-break for a soft hint, not a correctness
  guarantee.
- **Resumable, not idempotent-by-overwrite.** `extraction_progress.json`
  (`{chapter_count, next_chapter_index}`) is written after every chapter,
  same per-chapter durability as `facts.jsonl`'s flush - whatever
  interrupts a run (Ctrl+C, a dropped connection, a crash, or a genuine
  provider error that isn't caught per-chapter), the *next* `extract_book`
  call for the same `book_id` resumes right after the last chapter that
  actually finished (`facts.jsonl` opened `"a"` instead of `"w"`), instead
  of losing everything and restarting from chapter 0. A `chapter_count`
  mismatch (the book was re-ingested with different chapter boundaries
  since the progress was recorded) is treated as stale and ignored - the
  old indices no longer mean the same thing. The progress file is
  deliberately never deleted, including on full success -
  `next_chapter_index == chapter_count` doubles as an "already fully
  extracted" marker, so re-running `extract_book` on a completed book is a
  cheap no-op (`already_complete=True`) rather than silently repeating a
  run that can take hours. `restart=True` bypasses all of this and behaves
  exactly like the old unconditional `"w"`-mode overwrite. Deliberately
  scoped narrowly to "the same book, continuing an interrupted run" - it
  does not track which provider/model produced the saved progress, so
  resuming with a *different* provider/model than the interrupted run
  silently mixes them in one `facts.jsonl` (not validated against). Keeping
  multiple providers'/models' results side by side without this mixing is
  a separate, deliberately not-yet-designed feature - see Open Questions.
- **A brand-new entity must be named in the chapter that "introduces" it,
  or the fact is rejected** - real bug found running the full Ranger's
  Apprentice omnibus against `llama3.2:3b`: a real line about the
  protagonist got attached to "Arthur Penhaligon," a character from an
  entirely different book series, whose name never appears anywhere in
  that chapter's text. The check (`raw.entity_name.lower() in
  chapter.text.lower()`) only applies when `raw.entity_name not in
  known_names` - a fact about an *already-known* entity is accepted even
  if this specific chapter only refers to them by pronoun, since requiring
  the name to reappear in every chapter would reject perfectly good facts.
  Rejected facts are counted in `ungrounded_entity_count`, not silently
  dropped. See `test_extract_book_rejects_a_new_entity_never_named_in_its_chapter`
  and `..._does_not_reject_an_already_known_entity_referred_to_by_pronoun`.
- **A single chapter's `ExtractionParseError` is caught and skipped, not
  fatal** - real bug found running the full 75-chapter Ranger's Apprentice
  omnibus against `llama3.2:3b`: chapter 1 ("For Michael", a two-word
  dedication page) produced malformed output and crashed the entire run,
  losing all progress. Now that chapter is counted in
  `parse_failure_count` and skipped; every other chapter's facts are still
  written. `save_entities` runs in a `finally` so partial progress is kept
  even if some *other*, non-`ExtractionParseError` failure aborts the loop
  (e.g. the provider becoming unreachable mid-run, which is deliberately
  NOT caught per-chapter - retrying every remaining chapter against a dead
  provider would be pointless). See
  `test_extract_book_skips_a_chapter_with_malformed_provider_output`.
- **A chapter under `MIN_NARRATIVE_WORDS` (20) never reaches the provider at
  all** - real observed cases a small local model hallucinated facts for
  instead of recognizing as non-narrative: a 2-word chapter fragment, a
  ~9-word copyright address block, a ~5-word dedication. This is
  deterministic and doesn't depend on the model recognizing non-narrative
  content on its own. It's a floor, not a complete fix: a longer
  non-narrative fragment (this book's actual table-of-contents "chapter" is
  171 words, its copyright/legal page 133) is well above this threshold and
  relies on `prompts.EXTRACTION_SYSTEM_PROMPT`'s explicit "return `{"facts":
  []}` for non-narrative text" instruction instead - which a 3B model
  doesn't always follow (see Open Questions). Counted in
  `skipped_chapter_count`, surfaced by `cli.py` like the other counts here.
  See `test_extract_book_skips_very_short_chapters_without_calling_the_provider`.

## Data Contracts
- Fact record written to `facts.jsonl`: `{entity_id, chapter_index,
  category, statement}` (`book_id` is implicit from the file's directory,
  same convention as `chapters.jsonl`).
- `extraction_progress.json` (new): `{chapter_count: int, next_chapter_index:
  int}` - `chapter_count` is a staleness guard (see Key Decisions),
  `next_chapter_index` is where the next call resumes. Written after every
  chapter; never deleted, including on full completion (see Key Decisions
  for why that's deliberate).

## Dependencies
- Internal: `bookrag.extract.resolve` (entity load/save/resolve),
  `bookrag.providers.base.Provider`, `bookrag.storage` (`library_root`,
  `load_chapters`, `load_metadata`, `series_reading_order`)

## Open Questions / TODOs
- Not yet run against real chapters with `AnthropicProvider` - only
  `FakeProvider` so far (no API key available). Verify real
  output once a key/credential exists.
- `MIN_NARRATIVE_WORDS` only catches the shortest non-narrative fragments;
  a 100-200 word front-matter block (copyright page, table of contents)
  still reaches the provider and depends entirely on the prompt-side
  instruction to self-censor, which `llama3.2:3b` follows inconsistently in
  practice (it produced several grounded-but-unwanted facts about real ToC
  entries/publisher info on a re-extraction, rather than returning `{}`) -
  better than the wholesale fabrication seen before that prompt existed,
  but not a complete fix. A code-side heuristic to detect longer
  non-narrative fragments (vs. relying on prompt compliance) is a
  deliberately deferred follow-up, not attempted here.
- ~~No resume-from-abort exists.~~ **Resolved (2026-09-09)**: see the
  resumability Key Decision above. Deliberately scoped to the single-book,
  same-provider case only - the requested next step is a *multi-version*
  library (e.g. extract with a small local model now, later extract again
  with a bigger/better model without discarding the first, default to
  reading the better model's facts, possibly LLM-assisted comparison/
  consolidation between them later). That needs real design work (how
  `facts.jsonl`/`entities.json` represent "which model produced this," how
  `bookrag chat`/`library.py`'s summaries pick a default, whether
  `resolve_entity` needs to be model-scoped) and hasn't been started -
  flagged here as a future planning-pass item, not attempted
  as part of this narrower resumability fix.
- ~~No cap exists on facts-per-chapter or total facts-per-book.~~
  **Resolved**: this was actually the root cause of a real runaway-
  generation bug (a request generating 8,490+ output tokens over 14m43s
  before Ollama's own server gave up and restarted), not just a throughput
  concern - see `providers/parsing.py`'s context doc for the full
  diagnosis. Fixed with a hard `maxItems` cap on `extraction_response_schema()`'s
  `facts` array (originally 25, raised to 40 once that same full real
  75-chapter run showed the cap itself was routinely binding in the book's
  back half - see `providers/parsing.py`'s context doc), verified against a
  full real 75-chapter run with zero hangs. `DEFAULT_TIMEOUT_SECONDS`
  (300s→900s) remains raised as a separate, still-valid accommodation for
  the extraction prompt's legitimately higher output volume per chapter
  (not runaway, just more thorough) - see `ollama_provider.py`'s context
  doc.
- ~~The non-fiction taxonomy has only been validated via a `bookrag eval`
  checkpoint~~ **Updated (2026-09-09)**: since resolved by full real runs -
  Atomic Habits (36 chapters, 370 facts) and Finite and Infinite Games (18
  chapters, 277 facts) have both been fully extracted with
  `content_type="nonfiction"`, confirming the same quality/throughput
  characteristics observed for fiction hold here too (`MIN_NARRATIVE_WORDS`/
  `maxItems`/the timeout are genre-agnostic and needed no changes).
