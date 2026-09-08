---
source: src/bookrag/extract/pipeline.py
last_synced: 2026-09-08T00:00:00Z
source_hash: c4a29b4fc25a7566bdaa71ba2bb5bb0ed62d6b0e
---

## Purpose
The actual extraction pipeline: runs a `Provider` over every chapter of a
book, in order, resolving entities and writing `facts.jsonl` - the one
place `ExtractedFact`s (raw, provider-shaped) become `Fact` records (stored,
entity-resolved, chapter-scoped).

## Public Interface
- `ExtractionResult(book_id, chapter_count, fact_count, new_entity_count,
  parse_failure_count, ungrounded_entity_count, skipped_chapter_count)`
- `extract_book(book_id, provider, root=None, on_chapter_done=None) ->
  ExtractionResult` — overwrites `data/library/<book_id>/facts.jsonl` and
  updates `data/library/entities.json`. `on_chapter_done`, if given, is called as
  `on_chapter_done(position, total)` after every chapter (1-indexed
  `position`, including skipped/failed ones) - `cli.py` uses this to print
  progress with an ETA, but `pipeline.py` itself does no printing. Looks up
  the book's `content_type` via `storage.load_metadata(book_id, root).get(
  "content_type", "fiction")` once at the top and passes it to every
  `provider.extract_facts` call - not a per-chapter lookup, since a single
  book's content type doesn't change chapter to chapter.
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
- Chapters are processed **sequentially, never in parallel** - each
  chapter's `known_entities` list grows as facts are resolved, so chapter 5
  sees entities introduced in chapters 0-4. Parallelizing would break this
  incremental context (and, for the real Claude provider, chapters would
  race to append to the same `entities` dict).
- `known_entities` is seeded before chapter 0 from every **earlier** book in
  the series (`series_reading_order(book_id)[:-1]`) - this is what lets book
  2 of a series not re-introduce a character book 1 already established.
- Re-running `extract_book` on the same `book_id` overwrites `facts.jsonl`
  from scratch (`"w"` mode) rather than appending - re-extraction is meant
  to be idempotent per book, not additive.
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

## Dependencies
- Internal: `bookrag.extract.resolve` (entity load/save/resolve),
  `bookrag.providers.base.Provider`, `bookrag.storage` (`library_root`,
  `load_chapters`, `load_metadata`, `series_reading_order`)

## Open Questions / TODOs
- Not yet run against real chapters with `AnthropicProvider` - only
  `FakeProvider` in this environment (no API key available). Verify real
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
- **No resume-from-abort exists.** Confirmed directly today: a run that
  times out or crashes partway (see `ollama_provider.py`'s timeout history)
  has no recorded "last completed chapter" - the only way to continue is a
  full re-run from chapter 0, via the same `"w"`-mode overwrite noted above
  under Key Decisions. For a long book with slow per-chapter calls, an
  aborted run near the end currently means redoing all the fast, already-
  fine earlier chapters too. A checkpoint/resume mechanism (e.g. skip
  chapters already present in `facts.jsonl` unless forced) would directly
  address this, but wasn't built - it's a distinct feature, not something
  the current fix needed, and no one has asked for it yet.
- ~~No cap exists on facts-per-chapter or total facts-per-book.~~
  **Resolved**: this was actually the root cause of a real runaway-
  generation bug (a request generating 8,490+ output tokens over 14m43s
  before Ollama's own server gave up and restarted), not just a throughput
  concern - see `providers/parsing.py`'s context doc for the full
  diagnosis. Fixed with `maxItems: 25` on `extraction_response_schema()`'s
  `facts` array, verified against a full real 75-chapter run with zero
  hangs. `DEFAULT_TIMEOUT_SECONDS` (300s→900s) remains raised as a
  separate, still-valid accommodation for the extraction prompt's
  legitimately higher output volume per chapter (not runaway, just more
  thorough) - see `ollama_provider.py`'s context doc.
- The non-fiction taxonomy (`content_type="nonfiction"`) has only been
  validated via a `bookrag eval` checkpoint (3 chapters), not a full real
  extraction run the way fiction has (`ranger-s-apprentice-1-2-bindup`,
  75 chapters). Worth a full run once there's a reason to (e.g. actually
  wanting Atomic Habits' complete catalog), to see whether the same
  quality/throughput tradeoffs observed for fiction (see above) recur here
  too - `MIN_NARRATIVE_WORDS`/`maxItems`/the timeout are all genre-agnostic
  and apply unchanged.
