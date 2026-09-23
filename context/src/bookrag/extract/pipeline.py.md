---
source: src/bookrag/extract/pipeline.py
last_synced: 2026-09-23T00:00:00Z
source_hash: 9251348251207fdb6face8b4ad0c5c0c9667cd23
---

## Purpose
The actual extraction pipeline: runs a `Provider` over every chapter of a
book, in order, resolving entities and writing `facts.jsonl` - the one
place `ExtractedFact`s (raw, provider-shaped) become `Fact` records (stored,
entity-resolved, chapter-scoped).

## Public Interface
- `ExtractionResult(book_id, chapter_count, fact_count, new_entity_count,
  parse_failure_count, ungrounded_entity_count, skipped_chapter_count,
  duplicate_fact_count=0, resumed_from_chapter=None, already_complete=False,
  context_window=None)`
  — `resumed_from_chapter`/`already_complete` are for resumable extraction
  (see Key Decisions): `resumed_from_chapter` is the chapter index this
  call started at (`None` for a from-scratch run), `already_complete`
  means this call did nothing because a prior run already reached the end.
  `duplicate_fact_count` is how many raw facts this call dropped for being
  an exact repeat of an earlier fact in the same chapter (see Key
  Decisions) - `cli.py` surfaces it like the other counts here when
  nonzero. `context_window` is the window this run actually used after
  narrowing it from the book's own chapters, or `None` for a provider with no
  such setting (Anthropic, the fakes) - callers must read `None` as "nothing
  to report", never as a default.
- `context_window_for(chapters, *, ceiling, floor=MIN_CONTEXT_WINDOW,
  tokens_per_word=_TOKENS_PER_WORD) -> int` — the smallest sensible extraction
  context window for this book.
- `MIN_CONTEXT_WINDOW = 4096` — the floor.
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
  that chapter's text. The check only applies when `raw.entity_name not in
  known_names` - a fact about an *already-known* entity is accepted even
  if this specific chapter only refers to them by pronoun, since requiring
  the name to reappear in every chapter would reject perfectly good facts.
  Rejected facts are counted in `ungrounded_entity_count`, not silently
  dropped. See `test_extract_book_rejects_a_new_entity_never_named_in_its_chapter`
  and `..._does_not_reject_an_already_known_entity_referred_to_by_pronoun`.
  The matching rule itself is `_entity_is_grounded`, which is more than a
  substring test - see the next section for why it had to be.
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
- `extraction_progress.json`: `{chapter_count: int, next_chapter_index: int,
  provider?: str}` - `chapter_count` is a staleness guard (see Key
  Decisions), `next_chapter_index` is where the next call resumes. Written
  after every chapter; never deleted, including on full completion (see Key
  Decisions for why that's deliberate). `provider` is the
  `"<provider>:<model>"` identity that wrote these facts, e.g.
  `"ollama:qwen2.5:7b-instruct"`; **optional, and absent means "unknown",
  never "none"** - every book extracted before it was introduced has no such
  key, and those must stay resumable.

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

## Per-chapter durability of entities.json (added after real data loss)
`save_entities` now runs **inside** the chapter loop, in lockstep with
`facts.jsonl`'s flush, not only in the closing `finally`. The three
per-chapter writes have a deliberate order - facts flush, then entities save,
then `extraction_progress.json` - so that a death between any two of them
costs at most a re-processed chapter rather than leaving a chapter marked done
whose data was never persisted.

Why it changed: the `finally` is honoured by an exception unwinding, but not
by an abrupt kill. A real run terminated mid-chapter left **38 facts
(chapters 4-10 of `ranger-s-apprentice-1-2-bindup`) referencing entity_ids
that were never written to the registry.** The damage is permanent and
asymmetric:
- A fact record stores only `entity_id`; the name lived solely in
  `entities.json`. Nothing can recover it.
- Some of those entities were later re-created under *fresh* ids when a later
  chapter mentioned them again (Castle Redmont, Master Chubb) - so one real
  entity is split across two ids, with its early facts unreachable by
  entity-name retrieval.
- Others (Lady Pauline, Nigel, Ulf) were never re-created at all; their facts
  render as a raw `character-5049ebd0` and are invisible to the name matcher.

`library.run_doctor` detects this state (`unnamed_fact_refs`) but deliberately
never repairs it - see that file's context doc.

## Story-time fields on the written record
Each fact record now carries `when` (see `providers/parsing.py`'s context
doc), and `time_phrase` **only when the model supplied one** - omitted rather
than written as `null`, which is the common case. That keeps the line short
and leaves an older record, which has neither key, indistinguishable from a
new record that simply had no time to report; `query.facts_as_of` reads both
with defaults either way.

## Resume guard: refusing to mix two models' facts

`extract_book`'s docstring has always scoped it to *"the same book, the same
provider/model, continuing an interrupted run"* - nothing enforced it. A
resumed run with a different `--model`/`$OLLAMA_MODEL` silently appended one
model's facts to another's, producing a book whose facts disagree about a
character for reasons no reader can see and that nothing downstream records.
This nearly damaged the real library during development, which is why it was
promoted ahead of other Phase 1 work.

**Interface**
- `ExtractionResumeMismatch(recorded, current, next_chapter_index)` - raised
  by `extract_book`; its message names both models and both ways out.
- `recorded_extraction_identity(book_id, root=None) -> str | None` - the
  identity saved with a book's progress; same tolerant read as
  `resume_start_index` (missing/unreadable is `None`, not an error).
- `resume_blocker(book_id, provider, root=None, *, start_index) -> 
  ExtractionResumeMismatch | None` - the policy itself, **returned rather
  than raised** so `cli.py` can ask the question before printing
  `"Resuming from chapter N"`. One source of truth, two call sites with
  different needs: the CLI wants to report, the pipeline wants to stop.

**Key decisions**
- **Either identity being `None` means unverifiable, not mismatched.** A
  provider that doesn't identify itself and a book extracted before this
  existed must both stay resumable - refusing every pre-existing book would
  be a far worse bug than the one being prevented.
- **Checked after the already-complete short-circuit**, not before. A
  finished book writes nothing, so a different model cannot corrupt it, and
  *"already complete, pass `--restart`"* is both true and more useful than a
  mismatch error.
- **`--restart` is never blocked.** It discards the existing facts rather
  than appending to them, so there is nothing to mix - and it is one of the
  two ways out the refusal points at.
- **The refusal is deliberately non-recoverable.** Re-running with the
  original model and paying for a fresh full run are both the caller's
  decision; neither is a default this can pick for them.
- Resuming a progress file that had no identity **stamps the current run's
  identity** onto it. The earlier chapters' model is unknowable at that
  point, and recording the half that is knowable beats recording nothing.

## `_entity_is_grounded`: why the substring check had to go

The grounding check above was `raw.entity_name.lower() in
chapter.text.lower()` for most of its life. It failed open on exactly the
names most likely to be hallucinated: **a short name that is also an
ordinary English word.** `"Will"` is inside `"he will go"`.

This was found investigating a user-reported hallucination - a freshly
cloned install extracted an unrelated book and reported its protagonist was
*"nervous about the Choosing Day"*. The leak's source was
`providers/prompts.py`, whose worked example was written around Ranger's
Apprentice (fixed there, guarded by `tests/test_prompts.py`). But this check
is what should have caught the leak on the way out, and did not: measured
against the real Moby Dick chapters in the library, a hallucinated `"Will"`
was "grounded" by **111 of 147 chapters**, `"Art"` by 136, `"May"` by 100.
The guard was effectively off for the whole class.

`_entity_is_grounded(entity_name, entity_type, chapter_text)` replaces it
with three rules, each added to fix a measured problem rather than on
principle:

1. **Word boundaries.** `"Art"` no longer rides in on `"start"`.
2. **A proper noun must appear capitalized as written.** This is the only
   thing that separates the name `"Will"` from the verb, and it is safe
   because a character or place genuinely introduced in a chapter is
   capitalized there. Applied only to `_PROPER_NOUN_ENTITY_TYPES`
   (`character`, `setting`) - a model routinely title-cases a theme or
   concept (`"Courage"`, `"Anchoring"`) where the prose only ever says
   `"courage"`, so demanding the capital there would reject good facts.
3. **Singular/plural is not a grounding failure.** The stem is matched with
   an optional `(?:e?s)?` inflection, in both directions.

Rules 2 and 3 were *not* in the first version, and the real library is what
caught that. A naive word-boundary + case-sensitive check rejected 14
legitimate entities: `"Waste Person"` (the chapter says *"Waste persons
are..."*), `"academic field"` (*"Academic fields are such territories"*),
and descriptor-style names a model sometimes files as characters -
`"Old man"`, `"The rowers"`, `"Two intruders"` - which the prose honestly
keeps lowercase. So `_looks_like_a_proper_noun` narrows rule 2 to names that
actually look like names: first token capitalized, and every token either
capitalized or a connector (`of`, `the`, `de`, ...), so `"Castle Araluen"`
and `"The Ruins of Gorlan"` qualify while `"Old man"` does not.

**Measured on the real library** (4 books, 2,035 facts), final version:

| | old check | new check |
|---|---|---|
| chapters accepting a hallucinated "Will" | 111/147 | **11/147** |
| ... "Art" | 136/147 | **1/147** |
| ... "May" | 100/147 | **10/147** |
| ... "Halt" | 11/147 | **0/147** |
| real facts newly rejected | - | **6 / 1,857 (0.32%)** |

The residual `"Will"` acceptances are sentence-initial `"Will you..."`; this
is a heuristic guard, not a parser, and the prompt no longer contains that
name anyway. The 0.32% are all facts about entities grounded elsewhere in
the same book, which the check does not gate (it only gates *new* entities),
so the real-run impact is smaller still.

## Entity identity scope (added with `resolve_entity`'s `scope`)

`series_reading_order(book_id, root)` is now computed **once** into
`reading_order` and used for three things that must agree: the
`known_names` seed, the `known_types` seed, and the `scope` passed to every
`resolve_entity` call. If they disagreed the pipeline would contradict
itself - telling the provider a name is already known while resolving that
same name to a brand-new entity. See `extract/resolve.py`'s context doc for
the cross-book merges this closes.

## `--restart` prunes this book's entities

`restart=True` reopens `facts.jsonl` in `"w"` mode, discarding the previous
run's facts - so that run's entities have to go with them. Left in place they
are invisible damage: still seeded into `known_names`, still claiming this
book in `book_ids`, still counted by `bookrag show`, with not one fact behind
them. Real observed consequence: an entity whose registry row claimed a book
holding zero facts about it, which then looked indistinguishable from a
genuine cross-book merge (see `library.split_cross_book_entity`, which
handles exactly that shape).

Uses `prune_book_from_entities`, which strips only **this** `book_id`. An
entity an earlier series book also owns keeps that book and survives -
correct, since that book's facts were not discarded, and dropping it would
silently un-establish a character book 1 introduced.

Runs before `known_names`/`known_types` are built, so a restarted run is
seeded from what actually survives rather than from the discarded run.

## `entity_name` on every fact record
The raw name the model returned, stored alongside `entity_id`.

**This is what makes a merge reversible, and it is the real answer to "what if
two characters get combined?"** A record used to say only which entity owns a
fact; nothing said which surface form it arrived as, so two characters wrongly
merged could not be told apart again, let alone separated. A wrong merge was
permanent. It is now a reportable, undoable state. Costs one short field and no
model work - resolution already had the value. **Absent from records written
before this existed**, so readers must use `record.get("entity_name")`.

Also evidence the alias machinery works: after auto-linking the real reported
book, the raw names landing on one entity were Conn 67, Connwaer 55, Boy 28,
Thief 11 - the last two being facts that would otherwise have fragmented.

## Declared aliases are re-applied on every run
`extract_book` re-seeds `storage.load_declared_aliases(book_id)` **after** the
`--restart` prune, not before. The prune removes every entity the discarded run
created and cannot distinguish a seeded one, so seeding earlier is undone -
confirmed before this existed, where a restart turned a linked Conn/Connwaer
back into two entities. `seed_alias_group` is idempotent, so a normal resumed
run re-applies the same groups and changes nothing.

## Sizing the context window from the book

`extract_book` holds every chapter before it makes a single provider call, so
the largest prompt the run will ever send is knowable up front rather than
guessed at. `context_window_for` computes it - longest chapter's word count x
`_TOKENS_PER_WORD` + `_PROMPT_OVERHEAD_TOKENS` - rounds **up to a power of
two**, and clamps to `[floor, ceiling]`. `narrow_context_window` then applies
it to the provider, and only ever downwards.

Worth doing because `num_ctx` sizes the KV cache, which is the main lever on
whether a model fits in VRAM at all (~0.9GB between 4096 and 16384 for a 7B).
Measured on the real library: Ranger's Apprentice (longest chapter 3,865
words) drops from 16384 to **8192**, halving that cache; The Eye of the World
(longest 10,509 words, 43 chapters over 8,192 tokens) correctly stays at
**16384**. A flat 8192 for everyone would have broken the second book, which is
why this is computed per book rather than being a smaller constant.

- **`_TOKENS_PER_WORD = 1.25` is an estimate, deliberately not a real
  tokenizer.** Measured against Ollama's own `prompt_eval_count` on real
  chapters (1,737 tokens for 1,434 words). A real tokenizer would mean a new
  dependency, a model-specific vocabulary and a genuine correctness burden, to
  size a number that is then rounded up to a power of two and padded anyway -
  the rounding absorbs far more error than the estimate introduces.
- **`_PROMPT_OVERHEAD_TOKENS = 2600` is generous on purpose.** It covers the
  ~1,440-token system prompt plus the known-entities preamble, which grows
  through a book (measured: 269 characters at chapter 4, 780 by chapter 8, and
  still climbing). Under-sizing truncates a real chapter and silently loses
  facts; over-sizing costs only cache.
- **Rounded to a power of two** so two similar books don't end up with two
  gratuitously different cache sizes.
- **Only ever narrows** (enforced in `narrow_context_window`, not here), so a
  user who deliberately set a small `$OLLAMA_EXTRACT_NUM_CTX` never has it
  raised by a book that would like more room.
- Computed in **two places on purpose**: `cli.extract_start_notes` previews it
  so the user is told before a multi-hour run rather than after, and
  `extract_book` applies it as the real source of truth. Same shape as
  `resume_start_index`/`resume_blocker`, and safe because narrowing is
  idempotent.

## Splitting an oversized chapter across several calls

A chapter over `consolidate.SPLIT_THRESHOLD_WORDS` (3,500) is handed to the
provider in pieces - one `extract_facts` call each - instead of whole. Usually
this loop runs exactly once; measured on the corpus, it splits 1 of 75 chapters
in Ranger's Apprentice and 48 of 108 in The Eye of the World, and does nothing
at all to six of the eight books.

**Every fact from every piece is recorded against `chapter.index`.** That single
property is what makes the change safe: `query.facts_as_of`'s spoiler
filtering, `locate.cite`'s citations, `locate.volume_at`'s spans,
`extraction_progress.json`'s resume granularity and `chat --chapter N` all key
on `chapter_index`, and none of them can tell that a chapter was split. No book
needs re-ingesting. Splitting at ingest instead would change what a chapter *is*
and break all of them - see `ingest/consolidate.py`'s context doc.

Two details that are easy to get wrong:

- **`_entity_is_grounded` checks the WHOLE chapter's text, never the piece the
  fact came from.** A character named in piece 1 and described in piece 3 is
  grounded in the chapter; narrowing the check to the piece would reject them
  as hallucinated purely because of where a boundary happened to fall.
- **`parse_failure_count` counts failed *pieces*, not failed chapters.** A
  chapter whose pieces partly succeed still contributes its good facts, which
  is strictly better than losing the whole chapter to one bad response - but
  it does mean the count can exceed the chapter count on a split book.
- **The schema's `maxItems: 40` becomes a per-piece budget**, so a split chapter
  can return far more facts than an unsplit one. That is the intended relief for
  chapters that were being truncated, and simultaneously the thing to watch: the
  existing per-chapter exact-match dedup sits outside the provider call so it
  spans pieces for free, but it catches only verbatim repeats, not a
  near-duplicate rephrasing across a boundary. `eval.near_duplicate_pairs`
  exists to measure that.
