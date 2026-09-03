# Book_RAG

A tool that ingests `.epub`/`.pdf` novels and builds a spoiler-safe catalog of
characters, settings, and themes — each fact tagged with the chapter it was
revealed in, so a reference to chapter N never leaks what happens after it.
It can **ingest** books and **extract** facts about them; a natural-language
query/chat interface on top of the extracted facts hasn't been built yet
(the spoiler-safety filter it will use, `bookrag.query.facts_as_of`, has).

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
    measured at roughly 10-15s/chapter for short chapters, ~47 minutes for
    a full 75-chapter novel (`data/library/ranger-s-apprentice-1-2-bindup`).
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
```

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
- **Small local models are less reliable at strict JSON than Claude.**
  `llama3.2:3b`'s first real test produced a JSON array with a syntax error
  (missing comma). Mitigated by sending `"format": "json"` to Ollama, which
  constrains generation to always be syntactically valid - confirmed clean
  across 5 repeat runs after the fix - but a schema-conformance failure
  (right JSON, wrong keys) is still possible and surfaces as
  `ExtractionParseError`, visible in `bookrag eval`'s parse-failure count.
- **No natural-language query/chat interface yet.** `bookrag.query.facts_as_of`
  is the tested spoiler-safety primitive (never returns a fact past the
  given chapter), but there's no CLI command or RAG answer-synthesis layer
  on top of it yet - that's the next planned piece.
- **Small local models can hallucinate entity names - mitigated for new
  entities, not yet for facts about known ones.** Running the full
  75-chapter Ranger's Apprentice omnibus through `llama3.2:3b` correctly
  identified the real main cast (Will, Halt, Horace, Gilan, Evanlyn, Duncan,
  Erak, Morgarath, Alyss) but also produced "Arthur Penhaligon" - a
  character from an entirely different book series (Garth Nix's *Keys to
  the Kingdom*) - attached to a real line about Will not knowing his
  parentage. `extract_book` now rejects a fact naming a **brand-new**
  entity whose name doesn't literally appear anywhere in that chapter's
  text (this exact case is caught: "Arthur Penhaligon" never occurs in
  chapter 2), reporting the count as `ungrounded_entity_count`. This does
  **not** catch a hallucinated fact wrongly attributed to an
  **already-known** entity (e.g. misattributing someone else's line to
  Will, once Will is established) - that's a harder, unsolved problem, since
  requiring the name to reappear in every chapter would reject perfectly
  good pronoun-only references.
- **`entity_type` is now a strictly enforced, fixed list** -
  `{"character", "setting", "theme"}` only (`providers/parsing.py`). This
  isn't just tidiness: `resolve_entity` matches an existing entity by
  `(name, type)` together, so a drifting type string for the same real
  entity across extraction runs would silently fail to match and create a
  *duplicate* entity rather than reuse the one already known - unbounded
  type drift means unbounded entity drift. The real case found (`monster`/
  `creature` for Kalkara/Wargal) is folded into `character` via a small,
  explicit alias map; anything else is rejected as a parse failure rather
  than silently accepted, so a genuinely new category is a visible
  decision (add an alias), not something that just accumulates over time.
  Still a real constraint on the future query layer, though: querying
  "characters" must not become a strict `entity_type == "character"`
  filter that excludes `monster`/`creature`-derived entries folded into it -
  they're all stored as `"character"` today specifically so a query can't
  miss them.
- **No resumable extraction.** `bookrag extract` always starts from chapter
  0 and overwrites `facts.jsonl` from scratch - killing/interrupting a long
  run loses all progress, there's no "resume from the last completed
  chapter." Confirmed worth building: the sharpest case is a series
  ingested book-by-book, then later replaced or supplemented by a combined
  omnibus edition - long single-file extractions (or re-extractions after
  a partial run) are exactly where losing everything to one interruption
  hurts most.

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
