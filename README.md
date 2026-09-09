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
# from the project root
python -m venv .venv

# Windows (Git Bash)
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m pip install -e .

# macOS/Linux
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -e .
```

`requirements.txt` is a flat, pinned lock (generated via `pip freeze`) for
reproducible installs. `pyproject.toml` is the source of truth for dependency
*groups* (`core`, `providers`, `dev`) — if you change what the project
depends on, edit `pyproject.toml` first, then regenerate the lock:

```bash
./.venv/Scripts/python.exe -m pip install -e ".[core,providers,dev]"
./.venv/Scripts/python.exe -m pip freeze | grep -v -i "book_rag\|Editable install" > requirements.txt
```

### LLM provider setup

Three providers, chosen via `--provider`/`--providers` or `$BOOKRAG_PROVIDER`:

- **`ollama` (the default)** — local, no API key. Install
  [Ollama](https://ollama.com) (`winget install Ollama.Ollama` on Windows),
  make sure it's running (it starts automatically after install; check with
  `curl http://localhost:11434/api/version`), then pull a model:
  ```bash
  ollama pull llama3.2:3b
  ```
  This is the practical default for this project - the only confirmed
  Claude access here is an enterprise SSO seat, which doesn't provide a
  standalone script with an API credential.

  **Model selection is machine-specific, not hardcoded** - pick it via
  (in priority order) `bookrag extract --model NAME` (one-off), then
  `$OLLAMA_MODEL` (persistent, `.env` works), then `OllamaProvider.DEFAULT_MODEL`
  (`"llama3.2:3b"`, the fallback if neither is set). This matters because
  model size and inference speed trade off directly on CPU: every token
  requires a full pass through *all* the model's weights, so a bigger
  model isn't "smarter, therefore faster" - it does proportionally more
  arithmetic (and streams proportionally more weight data out of RAM) for
  every single token, with no shortcut. On a GPU that extra work is
  massively parallelized, so it costs much less wall-clock time than the
  raw parameter ratio suggests; on this machine's CPU-only AMD integrated
  graphics (no NVIDIA GPU), it doesn't get that break.

  - **This machine**: `llama3.2:3b` (3B params) is the practical choice -
    measured at roughly 20-90s/chapter depending on real chapter length and
    how much a chapter turns out to contain, ~2-2.5 hours for a full
    75-chapter novel (`data/library/ranger-s-apprentice-1-2-bindup`). This
    is slower than an earlier measurement of this same book (~47 minutes) -
    the extraction prompt was substantially reworked since then (explicit
    per-category definitions, self-containment requirements, a worked
    example) specifically to extract more thorough, better-categorized
    facts per chapter, and generating more content per chapter costs more
    wall-clock time. Confirmed worth it: `status`-category facts (milestone
    role/rank/life-condition changes) went from 5 across an entire book to
    483, and a real question that previously got a wrong or uncertain
    answer through `bookrag chat` ("has this character become an
    apprentice yet?") is now answered correctly.
  - **A machine with a GPU**: set `OLLAMA_MODEL` to something meaningfully
    larger (e.g. `qwen2.5:7b-instruct` or bigger) - larger models are
    generally more reliable at both instruction-following (respecting the
    fixed `entity_type` list) and reduced hallucination, and a GPU absorbs
    most of the extra cost that makes this impractical here. Confirm the
    improvement empirically before committing to a full-book run: `bookrag
    eval <book-id> --chapters N --model <candidate>` is fast (one chapter,
    not the whole book) and read-only.

    **Actually run on this machine**: `qwen2.5:7b-instruct` (7B) vs.
    `llama3.2:3b` (3B), same 3 chapters of the real Ranger's Apprentice
    omnibus - ~1.9x slower (28s → 53s/chapter, in line with the ~2.5x
    predicted from parameter count), but a real quality difference, not
    just a smaller model being "probably worse": on chapter 2 (a
    table-of-contents page with no real character content), `llama3.2:3b`
    hallucinated a fact anyway - **a different wrong name on two separate
    runs** ("Arthur Penhaligon," then "Arin," neither appearing anywhere in
    that text) - while `qwen2.5:7b-instruct` correctly returned `{}`
    (nothing to extract) both times. On chapters with real content, both
    correctly identified the right character (Will, Horace); qwen's
    statements were slightly more complete. Worth the ~2x time cost if
    hallucination on edge-case chapters matters to you; `llama3.2:3b`
    remains reasonable if throughput matters more and you're relying on
    `bookrag extract`'s existing safeguards (grounding check, strict
    `entity_type`) to catch what a smaller model gets wrong.
  - Override the Ollama host similarly via `$OLLAMA_BASE_URL` (e.g. to
    point at Ollama running on a different machine on the network instead
    of switching hardware at all).
- **`anthropic`** — real Claude via the API, for when a direct Anthropic
  Console key (or Bedrock/Vertex credential - not yet wired up, ask if
  needed) is available. Create a `.env` file in the project root
  (gitignored):
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

Drop a new book anywhere convenient before ingesting it - `data/incoming/` is
the suggested staging spot, purely for your own clarity (it's not required by
the tool, and nothing scans it automatically):

```bash
mv ~/Downloads/some-book.epub data/incoming/
```

```bash
# after activating the venv (or prefix with ./.venv/Scripts/python.exe -m bookrag.cli)
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
```

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
else. Facts are grouped by entity and category and tagged with the chapter
they came from (e.g. `[ch 9] has completed the Choosing Day`) so the model
has an explicit recency signal when two facts about the same specific
detail conflict (a status that changes over the course of the book) -
later chapters are treated as superseding earlier ones for the same detail,
never as contradictions to arbitrarily pick between. `--provider`/`--model`
work the same as `extract`. There's no multi-turn memory yet (each question
in an interactive session is answered independently) and no way to bump
`--chapter` mid-session - restart with a new `--chapter` value instead.

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
./.venv/Scripts/python.exe -m pytest tests/ -v
```

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
  items if it doesn't confidently choose to. Fixed with `maxItems: 25` on
  the schema's `facts` array (chosen from real observed data - the
  richest real chapter seen produced 32, itself an outlier). This is also
  why `bookrag extract` on a real book now takes meaningfully longer than
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
- **No fuzzy/semantic matching of entity names - naming-variant duplicates
  are a real, observed problem, not just a hypothetical one.** A single
  real extraction run produced separate entities for `Wargal`, `Wargals`,
  and `The Wargals` (the same creatures, referred to differently across
  chapters), further split across different `entity_type`s depending on
  how a given chapter phrased it. `resolve_entity` only does exact,
  case-insensitive string matching - it has no way to recognize these as
  the same thing. Consolidating duplicates and adding semantic/similarity
  search over facts (e.g. finding "the choosing ceremony" when the catalog
  calls it "the Choosing Day") is planned future work, not yet started.
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
- **No resumable extraction, and now a bigger deal than when this was
  first written.** `bookrag extract` always starts from chapter 0 and
  overwrites `facts.jsonl` from scratch - killing/interrupting a long run
  loses all progress, there's no "resume from the last completed chapter."
  This was already known to be worth building; it's more pressing now that
  a full real-book run takes on the order of 2+ hours (see "This machine"
  above) rather than under an hour - an interruption near the end costs
  much more than it used to.

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

## For future development sessions (Claude or human)

This project keeps a **mirrored context doc** under `context/<path>.md` for
every file under `src/` and `tests/`, summarizing purpose/interface/decisions
so you don't have to re-read full source just to know what a file does. For
files under `src/`, this is hook-enforced (a Claude Code `Stop` hook blocks
ending a turn while any file's context doc is out of sync) — see `CLAUDE.md`
for the full convention and template before editing source.
