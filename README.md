# Book_RAG

A tool that ingests `.epub`/`.pdf` novels and builds a spoiler-safe catalog of
characters, settings, and themes — each fact tagged with the chapter it was
revealed in, so a reference to chapter N never leaks what happens after it.
It can **ingest** books, **extract** facts about them, and answer
**natural-language questions** about a book through `bookrag chat`, which
never shows the answering model a fact from beyond the chapter you've
actually read (via `bookrag.query.facts_as_of`).

## Setup

Requires Python 3.11+.

```bash
git clone https://github.com/kherzai-3/Bookshelf.git Book_RAG
cd Book_RAG

# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python3 -m venv .venv
source .venv/bin/activate
```

Once the venv is activated, install dependencies (same command both OSes,
run from the project root):

```bash
pip install -r requirements.txt
pip install -e .
```

From here on, every command in this README assumes the venv is activated,
so `python`/`pip`/`bookrag` all resolve to the venv's own copies. If you'd
rather not activate it, prefix each command with the venv's interpreter
path instead (`.venv\Scripts\python.exe -m ...` on Windows,
`.venv/bin/python -m ...` on macOS/Linux).

`requirements.txt` is a flat, pinned lock (generated via `pip freeze`) for
reproducible installs. `pyproject.toml` is the source of truth for dependency
*groups* (`core`, `providers`, `dev`) — if you change what the project
depends on, edit `pyproject.toml` first, then regenerate the lock:

```bash
pip install -e ".[core,providers,dev]"
pip freeze --exclude-editable > requirements.txt
```

### LLM provider setup

Three providers, chosen via `--provider`/`--providers` or `$BOOKRAG_PROVIDER`:

- **`ollama` (the default)** — local, no API key required, which is why
  it's the default. Install [Ollama](https://ollama.com)
  (`winget install Ollama.Ollama` on Windows; `brew install ollama` on
  macOS, or the install script at [ollama.com/download](https://ollama.com/download)
  on Linux), make sure it's running (it starts automatically after install;
  check with `curl http://localhost:11434/api/version`), then pull a model:
  ```bash
  ollama pull qwen2.5:7b-instruct
  ```

  **Model selection is machine-specific, not hardcoded** - pick it via
  (in priority order) `bookrag extract --model NAME` (one-off), then
  `$OLLAMA_MODEL` (persistent, `.env` works), then `OllamaProvider.DEFAULT_MODEL`
  (`"qwen2.5:7b-instruct"`, the fallback if neither is set). Chat's
  answering model is a separate, independently-overridable knob - `bookrag
  chat --model NAME`, then `$OLLAMA_ANSWER_MODEL`, then
  `OllamaProvider.DEFAULT_ANSWER_MODEL` - same value as extraction's
  default today, but free to diverge later without any code changes.

  Bigger isn't automatically slower: every token requires a full pass
  through *all* the model's weights, so naively a bigger model does
  proportionally more arithmetic per token - but a real, controlled
  comparison on this project's own data found `qwen2.5:7b-instruct` was
  *not* slower than `llama3.2:3b` on the same real chapter (63s vs 78s) - a
  more selective model can generate fewer, more targeted output tokens and
  come out ahead despite doing more work per token. A GPU also
  parallelizes that per-token work, so a larger model costs much less
  wall-clock time there than the raw parameter ratio suggests.

  - **`qwen2.5:7b-instruct` (the default)** - the same real, controlled
    test found it both more reliable (`llama3.2:3b` showed genuine
    run-to-run variance - one run on a chapter produced zero facts about a
    character whose appearance is revealed in that exact chapter, a second
    identical run captured it well) and not slower. Still measured in the
    tens-of-seconds-per-chapter range, i.e. multiple hours for a full
    novel-length book, whether or not a GPU is available. `bookrag
    extract` is [resumable](#extracting-facts) specifically because of
    this - a long run doesn't need to happen in one sitting.
  - **On more constrained hardware**, fall back to a smaller model (e.g.
    `llama3.2:3b`) via `--model llama3.2:3b` / `$OLLAMA_MODEL` - faster per
    chapter on a machine that can't spare the RAM/VRAM for a 7B model, at
    the cost of the completeness/consistency found above. Confirm any
    model choice empirically before committing to a full-book run:
    `bookrag eval <book-id> --chapters N --model <candidate>` is fast (one
    chapter, not the whole book) and read-only, never touching
    `facts.jsonl`/`entities.json`.
  - **Chat's answering model can be tuned independently of extraction's** -
    a single question is one cheap one-shot call regardless of model size
    (~1-2s measured either way), so there's little downside to keeping it
    on the larger model even when extraction is pinned to something
    smaller for speed. Override via `bookrag chat --model NAME` or
    `$OLLAMA_ANSWER_MODEL`.
  - Override the Ollama host similarly via `$OLLAMA_BASE_URL` (e.g. to
    point at Ollama running on a different machine on the network instead
    of switching hardware at all).
- **`anthropic`** — real Claude via the API, for when a direct
  [Anthropic Console](https://console.anthropic.com) API key is available
  (Bedrock/Vertex credentials aren't wired up yet). Create a `.env` file in
  the project root (gitignored):
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  ```
  `AnthropicProvider` loads this automatically via `python-dotenv`. This key
  is unrelated to however you access Claude/Claude Code itself - `bookrag`
  is a standalone program that calls the API directly, so it needs its own
  credential, not a Claude.ai/Claude Code seat. Model likewise via
  `--model`/`$ANTHROPIC_MODEL`/`DEFAULT_MODEL` (`"claude-sonnet-5"`).
- **`fake`** — deterministic, no network, no setup. What the test suite
  uses; good for exercising the pipeline's plumbing without waiting on a
  real model.

## Usage

### Quickstart

One book, start to finish. `bookrag ingest` prints the `book_id` it assigns
(derived from the title) - copy it from there, or recover it later with
`bookrag list`:

```bash
bookrag ingest path/to/some-book.epub
# -> Ingested 'Some Book' as 'some-book' (12 chapters)

bookrag extract some-book --provider fake   # instant, no setup - swap in "ollama" for real extraction

bookrag chat some-book --chapter 3 --question "Who has appeared so far?"
```

Everything below is the full reference for each of these commands.

### Ingesting a book

Drop a new book anywhere convenient before ingesting it - `data/incoming/` is
the suggested staging spot, purely for your own clarity (it's not required by
the tool, and nothing scans it automatically):

```bash
mv ~/Downloads/some-book.epub data/incoming/
```

```bash
bookrag ingest data/incoming/some-book.epub
bookrag ingest path/to/book.pdf --title "Custom Title" --author "Someone"

# books in a series: chapters are always scoped per-book, so two books can
# each have their own "chapter 2" without collision. --series-position is
# required whenever --series is given.
bookrag ingest book1.epub --series "The Saga" --series-position 1
bookrag ingest book2.epub --series "The Saga" --series-position 2

# self-help, philosophy, or other non-narrative books - selects a different
# category/entity taxonomy for extraction (see below). Defaults to
# "fiction" - not auto-detected, so this must be passed explicitly.
bookrag ingest atomic-habits.epub --content-type nonfiction
```

**Fiction vs. nonfiction content:** `bookrag extract`'s category/entity
taxonomy is fundamentally different depending on `--content-type`, because
a novel's characters/settings/themes and a self-help book's concepts/
techniques/claims don't map onto the same schema - forcing nonfiction
content through the fiction categories was confirmed (via a real
before/after `bookrag eval` comparison) to actively misfile generic
illustrative examples ("desk," "phone," "bedroom") as if they were
meaningful recurring story *settings*. `--content-type nonfiction` gives
`extract`/`eval`/`chat` an entirely different set of categories instead
(`definition`, `claim`, `technique`, `example`, `relationship`,
`description`) and entity types (`character`, `concept`, `theme` - no
`setting`), with their own extraction/answer prompts. Set once at ingest
time, in `metadata.json` - not something you choose again later.

Each ingest prints a **sanity summary** (chapter count, word-count spread,
first/last chapter titles) and writes it, plus a **classification**, to
`data/library/<book_id>/ingestion_report.txt` for later review:
- `chapter-bound` — most chapters carry a real title (a heading/TOC signal
  was found); the chapters correspond to the book's real chapters.
- `text-bound` — little/no title signal, so extraction fell back to raw
  page/spine fragmentation (see Known limitations). **Chapter-scoped
  cataloging and spoiler-safe querying still work correctly in this case**
  — every chapter still has a stable index, `bookrag extract`/`facts_as_of`
  don't care whether a chapter's boundary lines up with the book's own
  chapter numbers or ToC, only that it has *a* consistent position. The
  fragments just won't read as "real" chapters if you look at their titles.
  If the fragments are also *implausibly small* (well under a real
  chapter's length - real case: a page-scanned epub with one physical page
  per fragment), ingestion automatically consolidates many small fragments
  into larger, more coherent ones before this classification even runs -
  printed at ingest time and noted in the report when it happens.

Title/author are resolved in this order: explicit flag > the file's own
internal metadata > best-effort guess from the filename (e.g.
`Some-Book-by-An-Author.pdf` → title "Some Book", author "An Author").

A parse/save failure (corrupt file, disk error, etc.) prints a one-line
error and exits 1 - it does not crash with a raw traceback, and never
leaves a partially-written `book_id` directory behind (either the ingest
fully succeeds or nothing is written at all).

On success, if the source file lives under `data/incoming/` (or whatever
`$BOOKRAG_INCOMING_ROOT` points to), it is **deleted** - it's now safely
copied into the library, so there's no reason to keep the staging copy. A
source file ingested from anywhere else is never touched.

### Extracting facts

Once a book is ingested, extract chapter-scoped facts about its characters,
settings, and themes:

```bash
bookrag extract <book-id>                             # uses $BOOKRAG_PROVIDER or "ollama"
bookrag extract <book-id> --provider anthropic        # if you have a real API key
bookrag extract <book-id> --provider fake             # instant, deterministic, for trying the pipeline
bookrag extract <book-id> --model qwen2.5:7b-instruct # one-off model override (see LLM provider setup)
bookrag extract <book-id> --restart                   # ignore saved progress, re-extract from chapter 0
```

**Resumable.** If a run gets interrupted - Ctrl+C, a dropped connection, a
crash - the next `bookrag extract <book-id>` (same book, same command)
picks up right after the last chapter that actually finished, instead of
losing everything and starting over. Progress is saved after every
chapter, so a long run on a slower model doesn't need to happen in one
sitting - useful for selectively working through a long book over several
shorter sessions rather than needing a single, potentially 50-hour one.
Running `extract` again on an already-fully-extracted book is a no-op by
default (prints a message and exits) rather than silently repeating a run
that can take hours; pass `--restart` to force a genuine from-scratch
re-extraction. This is scoped to the same book/same provider continuing
an interrupted run - it does not track *which* provider/model produced
the saved progress, so resuming with a different one than the interrupted
run mixes both in the same `facts.jsonl`. Keeping multiple providers'/
models' extractions side by side without overwriting each other (e.g. a
fast local model now, a better model later, defaulting to the better
one's facts) is a separate, bigger feature that needs its own design pass
- not yet built (see Future ideas).

For a series, extract books **in series order** — each book's extraction
seeds its "already-known entities" context from every earlier book in the
series (via `series_reading_order`), so book 2 doesn't re-introduce a
character book 1 already established.

Compare provider output on the same chapters without touching real data
(`eval` never writes to `facts.jsonl`/`entities.json`):

```bash
bookrag eval <book-id> --chapters 0,1,2 --providers ollama,fake
```

This prints a side-by-side report (fact count, sample statements per
provider per chapter) plus an automated **groundedness score** per
provider — a cheap lexical check (do a fact's key words actually appear in
the chapter text), not a semantic judge. Meaningful even with one provider
configured; more useful once a second (e.g. local-model) provider exists.

### Chatting with a book

Once a book has been extracted, ask it questions - spoiler-safe up to
whatever chapter you specify:

```bash
# one-off question, then exit
bookrag chat <book-id> --chapter 20 --question "Who is Halt?"

# interactive session - drop --question, get a `> ` prompt, Ctrl+C to exit
bookrag chat <book-id> --chapter 20
```

`--chapter` (0-indexed, required) is the reader's current position - facts
from later chapters are never shown to the answering model, going through
the same `facts_as_of` primitive that guarantees spoiler-safety everywhere
else. Before rendering, facts are filtered to just the entities your
question actually names (`query.select_relevant_facts` - exact name/alias
match, then light normalization so "Wargal" finds an entity named
"Wargals", then a small fuzzy fallback for typos); a question that doesn't
name anything specific still sees every known fact, same as before this
existed. This keeps a chat session's context size roughly independent of
how large the book's fact catalog has grown, not just proportional to it.
Facts are then grouped by entity and category and tagged with the chapter
they came from (e.g. `[ch 9] has completed the Choosing Day`) so the model
has an explicit recency signal when two facts about the same specific
detail conflict (a status that changes over the course of the book) -
later chapters are treated as superseding earlier ones for the same detail,
never as contradictions to arbitrarily pick between. `--provider`/`--model`
work the same as `extract`. There's no multi-turn memory yet (each question
in an interactive session is answered independently, though each now gets
its own freshly-filtered context) and no way to bump `--chapter` mid-session
- restart with a new `--chapter` value instead.

### Managing your library

```bash
bookrag list                    # every book: chapters, content type, extraction status, series
bookrag show <book-id>          # full detail for one book, including entity count

bookrag remove <book-id>        # asks for confirmation, then deletes the book + its facts
bookrag remove <book-id> --yes  # skip the confirmation prompt

bookrag doctor                  # read-only consistency check
bookrag doctor --fix            # apply the safe, obvious cleanups it finds
```

`list`/`show` report extraction status as *how far the run reached*, not
just "has any facts" - a chapter that genuinely has zero facts (front
matter, a too-short interstitial `extract.pipeline` skipped) doesn't make an
otherwise-complete book look partial. A real sample extraction (fewer
chapters attempted than the book has) shows as `N (partial: M/total ch)`.

`remove` deletes a book's library directory, its entry in `index.json`, and
prunes it from every entity's `book_ids` in the shared `entities.json`
registry - an entity left with no books after that is deleted outright.

`doctor` checks for the kind of drift that accumulates from hand-editing
library files directly (something this project's own development has done
more than once): an `index.json` entry whose directory is gone, an entity
still listing a `book_id` that no longer exists, and an entity with zero
facts referencing it in any book that's still around. It's read-only unless
you pass `--fix`.

### Where books end up

```
data/incoming/                # staging spot for files not yet ingested - a
                               # file here is DELETED once successfully ingested
data/library/<book_id>/
  source.epub | source.pdf   # the original file, copied in
  metadata.json               # title, author, series, chapter_count, ...
  chapters.jsonl              # one {index, title, text} object per line
  ingestion_report.txt        # classification (chapter-bound/text-bound) +
                               # the same info as the printed sanity summary
  facts.jsonl                 # one {entity_id, chapter_index, category, statement}
                               # per line, written by `bookrag extract`
data/library/index.json       # every ingested book, for listing/grouping by series
data/library/entities.json    # global entity registry: entity_id -> canonical
                               # name/type/aliases/which book_ids it appears in
```

`data/` is gitignored — it's local data, not source.

## Running tests

```bash
pytest tests/ -v
```

(with the venv activated - see Setup - or `.venv\Scripts\python.exe -m pytest tests/ -v` /
`.venv/bin/python -m pytest tests/ -v` if not)

## Known limitations

- **Epub chapter detection** splits each spine document by heading
  (`h1`/`h2`/`h3`) when it has more than one, which fixes books that bundle
  many chapters per file (e.g. Project Gutenberg), but front/back matter
  (title page, license text) can show up as a few extra low-value
  pseudo-chapters if it also carries heading tags.
- **Some epubs have no exploitable structure at all** - no heading markup
  and an empty navigation TOC (seen in practice: a real commercial epub,
  "Atomic Habits"). `load_chapters` then returns one chapter per spine
  file, which may be an arbitrary page-sized fragment unrelated to real
  chapters (286 untitled fragments for a ~20-chapter book). There's no fix
  for this without inventing a guess - the sanity summary's "first"/"last"
  titles being uniformly `(untitled chapter N)` is the signal to notice it.
- **PDF chapter detection** relies on the PDF's outline/TOC (bookmarks); if
  a PDF has no TOC, or the TOC entries are themselves meaningless (seen in
  practice: a PDF whose TOC entries were internal tool-generated bookmark
  IDs rather than real titles), chapter titles will be low-quality even
  though chapter boundaries may still be roughly right.
- No de-duplication across repeated ingests of the same book — re-ingesting
  the same file creates a second `book_id` (e.g. `the-hobbit-2`).
- **No cleanup/trim tool exists yet.** The sanity summary printed after
  ingest is diagnostic only - if it reveals bad chapters (front/back-matter
  noise, junk titles), there is currently no command to fix them up; the
  only lever today is re-ingesting with different `--title`/`--author`
  flags, which does not touch chapter boundaries at all. A `bookrag trim
  <book-id>` (or similar) command is a known gap, not yet built.
- **No fuzzy entity coreference.** `bookrag extract` resolves entity names
  via case-insensitive exact match only - "the old man" won't automatically
  link to a character already known as "Ishmael" unless the provider's own
  output happens to name them consistently. Aliases can be added to
  `data/library/entities.json` by hand today; automatic linking is future work.
- **Small local models are less reliable at strict JSON than Claude -
  mitigated with real, grammar-level structural guarantees, not just a
  request.** `llama3.2:3b`'s first real test produced a JSON array with a
  syntax error (missing comma). `OllamaProvider.extract_facts` now sends a
  full JSON Schema (`parsing.extraction_response_schema()`) as Ollama's
  `format` field (Ollama 0.33.2+), not just the string `"json"` - this
  grammar-constrains sampling so `entity_type`/`category` can never drift
  outside their enums and a fact's `statement` can't exceed a length cap,
  verified empirically to hold even adversarially. A schema-conformance
  failure is still possible for providers that don't schema-constrain
  (Anthropic, or Ollama's dict-wrapping quirks) and surfaces as
  `ExtractionParseError`, visible in `bookrag eval`'s parse-failure count.
- **An open-ended schema array under grammar-constrained decoding can
  cause runaway generation, not a clean failure.** Real, diagnosed case: a
  request generated 8,490+ output tokens (normal chapters produce
  500-1500) over nearly 15 minutes before Ollama's own server gave up and
  restarted - traced via Ollama's own logs to a fact array with no upper
  bound, which gives the model no structural reason to ever stop adding
  items if it doesn't confidently choose to. Fixed with a hard `maxItems`
  cap on the schema's `facts` array - originally 25 (chosen from real
  observed data, the richest chapter seen at the time produced 32, itself
  thought to be an outlier), raised to 40 once a full real 75-chapter run
  showed the cap itself routinely binding in the book's back half. This is
  also why `bookrag extract` on a real book now takes meaningfully longer
  than
  it used to (see "This machine" above) - both because more thorough
  extraction naturally produces more output, and because the request
  timeout (`OllamaProvider.DEFAULT_TIMEOUT_SECONDS`) was raised to 900s to
  give a legitimately long chapter room to finish.
- **Small local models can hallucinate entity names - mitigated in layers
  for brand-new entities, not for re-mentions of already-known ones.**
  Running the full 75-chapter Ranger's Apprentice omnibus through
  `llama3.2:3b` once produced "Arthur Penhaligon" - a character from an
  entirely different book series (Garth Nix's *Keys to the Kingdom*) -
  attached to a real line about Will, extracted from a chapter whose only
  content was a bare table of contents. Three defenses now apply: (1)
  `extract.pipeline.MIN_NARRATIVE_WORDS` skips calling the provider at all
  for the shortest non-narrative fragments (a floor, not a full fix - a
  100+ word front-matter block still reaches the model), (2) the
  extraction prompt explicitly instructs returning `{"facts": []}` for
  non-narrative text, (3) `extract_book` rejects a fact naming a
  **brand-new** entity whose name doesn't literally appear anywhere in
  that chapter's text (`ungrounded_entity_count`). Together these stopped
  that exact case from recurring on re-test. What remains unsolved: a fact
  wrongly attached to an **already-known** entity in a chapter that
  doesn't actually discuss them - real observed case: a table-of-contents
  chapter re-referenced a publisher/author/cover-credit entity that was
  legitimately established on an earlier copyright-page chapter, producing
  low-value noise (not fabrication - every name involved is real and was
  genuinely mentioned somewhere in the book). Gating re-mentions the same
  way as brand-new entities isn't a fix - it would reject perfectly good
  pronoun-only references to a character introduced chapters earlier.
- **`entity_type` is now a strictly enforced, fixed list, and `category` is
  schema-enum-constrained (Ollama) but leniently normalized elsewhere** -
  `entity_type` ∈ `{"character", "setting", "theme"}`, `category` ∈ the six
  documented values (`providers/parsing.py`). `entity_type` matters for
  correctness, not just tidiness: `resolve_entity` matches an existing
  entity by `(name, type)` together, so a drifting type string for the same
  real entity across extraction runs would silently fail to match and
  create a *duplicate* entity rather than reuse the one already known - the
  real case found (`monster`/`creature` for Kalkara/Wargal) is folded into
  `character` via a small alias map; anything else is rejected as a parse
  failure. `category` doesn't gate identity the same way, so an
  unrecognized value (real observed drift, pre-schema: `"location"`,
  `"author"`) is folded into `"description"` instead of rejecting the whole
  fact - the Ollama schema's `enum` prevents this drift structurally going
  forward, but the lenient fallback stays as a net for providers that don't
  schema-constrain.
- ~~No fuzzy/semantic matching of entity names~~ **Partially resolved.** A
  real extraction run had produced separate entities for `Wargal`,
  `Wargals`, and `The Wargals` (the same creatures, referred to differently
  across chapters), further split across different `entity_type`s depending
  on how a given chapter phrased it. `resolve_entity` now normalizes a
  leading "the " and a trailing "s" before comparing (`extract.resolve.match_key`)
  so simple spelling/plural variants of the *same* `entity_type` unify going
  forward, and known entities are now given their established type as a
  prompt hint so a recurring one is less likely to be re-typed differently
  each chapter. `bookrag doctor` also detects existing duplicate clusters
  (regardless of type) and `bookrag doctor --merge-duplicates` merges them
  with confirmation - run once against this project's own real library, it
  found and cleaned up 12 real clusters, not just the Wargal case that
  motivated it. What's still not done: real semantic/similarity search (e.g.
  finding "the choosing ceremony" when the catalog calls it "the Choosing
  Day") - `bookrag chat`'s `select_relevant_facts` does cheap substring/
  normalization/fuzzy matching against known entity names (see "Chatting
  with a book" above), not embedding-based search over fact content; that
  remains future work (see Future ideas).
- **Entity resolution is scoped to the whole library, not to a series.**
  `resolve_entity` matches purely on `(name, entity_type)`, with no check
  that the books involved are actually related - intentional for the series
  case (a character's facts should accumulate across sequential books), but
  it applies globally: two entirely unrelated books that each introduce a
  same-named, same-typed entity would silently share one `entity_id` in
  `entities.json`. Each book's own `facts.jsonl` stays correctly scoped
  regardless (this isn't a spoiler-safety issue), but the shared entity
  registry would conflate two different identities. Not yet observed in
  practice (no two books in the current library share a character name);
  noted here so it isn't rediscovered from scratch if one ever does.
- ~~No resumable extraction~~ **Resolved (2026-09-09)** - see "Extracting
  facts" above. Scoped narrowly to the same book/same provider continuing
  an interrupted run; it doesn't validate that a resumed run uses the same
  provider/model as the interrupted one, and it isn't a multi-version
  system (running a bigger model later without discarding a smaller
  model's results - see Future ideas).
- **`bookrag chat`'s recency-conflict rule can conflate two different real
  events, not just an updated status for the same one.** Real observed
  case: asked "what happened to Halt during the fight with the Kalkara?" (a
  real ch.33-36 event), the answer pulled in an unrelated ch.66 fact
  ("killed in the attempt to stop the Skandians" - a separate battle
  entirely) and concluded Halt died fighting the Kalkara, which isn't what
  happened. `ANSWER_SYSTEM_PROMPT`'s instruction to trust the LATER chapter
  when two same-category facts about the same entity conflict has no way
  to distinguish an actual status update from two unrelated occurrences
  that just happen to share a category and entity. Not yet investigated or
  fixed.

## Future ideas (need a planning pass before building)

- **Image generation** - illustrating characters/settings from the
  extracted catalog (e.g. a character portrait grounded in their
  accumulated `facts.jsonl` description, spoiler-scoped the same way text
  queries are). Not scoped yet - needs a design pass on how generation
  would consume the catalog, how spoiler-safety extends to images, and
  which backend to target. Two directions raised, neither committed to:
  - A hosted image-generation model/API.
  - A self-hosted integration (e.g. Stable Diffusion), consistent with the
    project's "no API key required" local-first posture (`ollama` is the
    default LLM provider for the same reason).
- **Multiple fact-library "versions" per book, keyed by which model
  produced them.** Today, extracting a book a second time with a different
  provider/model overwrites (`--restart`) or silently mixes with
  (resuming) the first run's facts in the same `facts.jsonl` - there's no
  way to run a fast local model now and a bigger/better model later
  without losing the first result. The idea: keep both, default reads
  (`bookrag chat`, `library.py`'s summaries) to whichever is considered
  "best" (assumed to be the larger/better model), and eventually support
  LLM-assisted comparison/consolidation between two models' takes on the
  same chapter. Real design questions, not yet worked through: how
  `facts.jsonl`/`entities.json` represent "which model produced this" (a
  suffix per book_id? a field on each fact/entity? a subdirectory per
  model?), whether `resolve_entity` needs to become model-scoped, and how
  a user picks/overrides the default when they want to see the smaller
  model's version instead. Needs its own planning pass before building.
- **Real embedding-based semantic search over fact content**, as a
  successor to `select_relevant_facts`'s current cheap substring/
  normalization/fuzzy name matching (see "Chatting with a book"). Would
  handle a genuinely topical or paraphrased question with no name overlap
  at all (e.g. "who are the antagonists?" or "the choosing ceremony" when
  the catalog calls it "the Choosing Day"), which name-based matching
  structurally can't. Likely direction: embed fact statements via Ollama's
  own embedding-model support (avoiding a heavy new ML dependency) and
  retrieve top-K by similarity - deliberately deferred rather than built
  alongside the cheaper fix, since the real, observed problem (a book's
  full context silently overflowing the model's window) is already solved
  by the cheaper approach for anything that names a specific entity, and
  this is a meaningfully bigger lift (an embedding step that needs to stay
  incremental/resumable alongside extraction, a similarity-search code
  path, cache invalidation when facts change).

## For future development sessions (Claude or human)

This project keeps a **mirrored context doc** under `context/<path>.md` for
every file under `src/` and `tests/`, summarizing purpose/interface/decisions
so you don't have to re-read full source just to know what a file does. For
files under `src/`, this is hook-enforced (a Claude Code `Stop` hook blocks
ending a turn while any file's context doc is out of sync) — see `CLAUDE.md`
for the full convention and template before editing source.
