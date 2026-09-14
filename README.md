# Book_RAG

A tool that ingests `.epub`/`.pdf` novels and builds a spoiler-safe catalog of
characters, settings, and themes — each fact tagged with the chapter it was
revealed in, so a reference to chapter N never leaks what happens after it.
It can **ingest** books, **extract** facts about them, and answer
**natural-language questions** about a book through `bookrag chat`, which
never shows the answering model a fact from beyond the chapter you've
actually read (via `bookrag.query.facts_as_of`).

## Setup

### Prerequisites

Install these yourself first — no script here installs them for you:

1. **Python 3.11 or newer** — [python.org/downloads](https://www.python.org/downloads/).
   Anything older fails immediately with a message saying so.
2. **[Ollama](https://ollama.com/download)** — *optional, but needed for real
   extraction and chat*. `winget install Ollama.Ollama` (Windows),
   `brew install ollama` (macOS), or the install script (Linux). It starts
   automatically after installing; confirm with
   `curl http://localhost:11434/api/version`.

Without Ollama you can still ingest books and exercise the whole pipeline with
`--provider fake`. You can also add it later — nothing has to be redone.

Then pick **either** setup path below. They produce the same result; the
installer is a convenience, not a requirement.

### Option A — one command

```bash
git clone https://github.com/kherzai-3/Bookshelf.git Book_RAG
cd Book_RAG

python install.py        # Windows
python3 install.py       # macOS/Linux
```

`install.py` creates `.venv`, installs the pinned dependencies and `bookrag`
itself, copies `.env.example` to `.env`, creates `data/incoming/` and
`data/library/`, verifies the `bookrag` command runs, then reports whether
Ollama is reachable and whether the default model is pulled — offering to
download it if not.

**The model download is the only thing it ever asks you.** It prompts only when
Ollama is running and `qwen2.5:7b-instruct` isn't pulled yet, because that is a
multi-GB download that shouldn't start unasked. Answer `y` and it downloads;
everything else is automatic. So the full path is: install Python, install
Ollama, run `install.py`, accept the download.

```bash
python install.py --pull-model     # answer yes in advance (fully unattended)
python install.py --no-pull-model  # never download it, don't even ask
python install.py --skip-ollama    # skip the Ollama check entirely
python install.py --run-tests      # also run the test suite afterwards
python install.py --recreate       # delete and rebuild .venv from scratch
python install.py --skip-doc-check # skip the context-doc freshness check
```

It never touches anything outside the project directory, never installs Python
or Ollama, and never writes outside `.venv`, `.env`, and `data/`. Ollama being
absent is a warning, not a failure. It also checks that every
`context/<path>.md` still matches the source file it describes (see "For future
development sessions" below) — a contributor-facing check that never affects
the install.

### Option B — by hand

Exactly what Option A automates, if you'd rather run it yourself:

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
cp .env.example .env            # optional; every setting in it is optional too
mkdir -p data/incoming data/library
ollama pull qwen2.5:7b-instruct # only if you installed Ollama
```

### Updating

```bash
git pull
python install.py       # or, for Option B: pip install -r requirements.txt
```

Re-running the installer is the update path — `.venv` and `.env` are reused,
never overwritten, and dependencies are re-resolved so a changed
`requirements.txt` is picked up. Because `bookrag` is installed in editable
mode, changed Python source is already live without reinstalling anything. Your
library under `data/` is never touched; it is not part of the install.

You only need `--recreate` if the venv itself is broken or the required Python
version changed.

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
#    ...then prints the exact extract command to run next, and how to watch it

bookrag extract some-book --provider fake   # instant, no setup - swap in "ollama" for real extraction

bookrag chat some-book --chapter 3 --question "Who has appeared so far?"
```

`ingest` only reads the book into the library — it does not extract anything.
It ends by naming the `bookrag extract` command to run next, since that is a
separate step and a much longer one (see
[Following a long run](#following-a-long-run)).

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

Each ingest ends by printing the **next command to run** — `bookrag extract
<book-id>`, with a warning about how long it takes and the exact commands for
backgrounding it and following the log (see
[Following a long run](#following-a-long-run)). Ingesting never extracts
anything itself, so this is a separate step you have to run.

Each ingest also prints a **sanity summary** (chapter count, word-count spread,
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
bookrag extract <book-id> --log                       # also tee output to a log you can tail (see below)
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

#### Following a long run

Extraction is the slow step: a local model takes on the order of minutes per
chapter, and a real 75-chapter novel measured **5h27m** end to end on a
mid-range laptop — **CPU-only** (see [GPU or CPU](#gpu-or-cpu)). That is long
enough that you will want it in the background — which is exactly when the
per-chapter progress lines stop being visible.

`--log` tees this run's output to a file as well as the console, so you can
background it and still watch:

```bash
bookrag extract <book-id> --log
# -> Logging to <tempdir>/extract_<book-id>.log
```

Then, in another terminal:

```bash
tail -f "$TMPDIR/extract_<book-id>.log"            # macOS/Linux
tail -f "$TEMP/extract_<book-id>.log"              # Windows, Git Bash
Get-Content -Wait "$env:TEMP\extract_<book-id>.log"  # Windows, PowerShell
```

`bookrag ingest` prints the resolved path for you, so you don't have to
construct it. Pass `--log PATH` to choose a different file. The log is
**appended**, not truncated — an interrupted run is resumed with the same
command, and the earlier attempt's output is usually what you want when working
out why it stopped.

Each line is flushed as it's written, so a follower sees progress as it
happens rather than in buffered bursts.

To detach the run entirely:

```bash
# macOS/Linux, Git Bash
bookrag extract <book-id> --log &

# PowerShell
Start-Process bookrag -ArgumentList "extract","<book-id>","--log" -NoNewWindow
```

Ctrl+C in a foreground run is safe — progress is saved after every chapter and
re-running the same command resumes (see **Resumable** above).

#### GPU or CPU

**bookrag never chooses this.** It does no inference of its own — it POSTs to
Ollama and Ollama decides, weighing free VRAM against the model plus its KV
cache when it loads. There is no "use the GPU" setting here to turn on.

What bookrag does do is **tell you**, once, after the first chapter:

```
  [1/75] chapter done - elapsed 59s, ~72m remaining
  NOTE: this run is on CPU only - no part of the model is on a GPU.
  Expect hours for a full-length book. ...
```

It reports after chapter 1 rather than up front because Ollama can only say
where a model sits once it has loaded one, and forcing a multi-GB load before
any work starts would be the worse trade. A run fully on the GPU says so in one
line and warns about nothing.

To check yourself, while a run is going:

```bash
ollama ps
```

Read the **label after the numbers** — `30%/70% CPU/GPU` means 70% on the GPU.
A split like that is not 70% of GPU speed: the CPU-resident layers gate every
token, so partial offload lands much closer to CPU speed than to GPU speed.
Getting to a full offload is worth real effort.

**Is a full offload even possible on this machine?** One number decides it:
free VRAM versus the ~4.7 GB of model weights.

- **Free VRAM comfortably above ~5.2 GB** — a full offload is reachable
  *without touching the model at all*. Everything that has to shrink is cache
  and overhead; see the levers below.
- **Free VRAM below ~4.7 GB** — the weights alone don't fit. No amount of cache
  tuning changes that, and a smaller model (or more VRAM) is the only path.

Check with `nvidia-smi` / `rocm-smi`, or Task Manager → Performance → GPU →
*Dedicated GPU memory* (see the warning below about which numbers there are
trustworthy). If you're partially or entirely on CPU, the levers are:

- **Lower `$OLLAMA_NUM_CTX`.** This is the only knob on bookrag's side that
  moves the needle, because it sizes the KV cache. Measured on a 7B model:
  **5.94 GB at `num_ctx=16384`** (the default) versus **5.06 GB at 4096** — so
  nearly a gigabyte of VRAM. If the model *almost* fits, this is the first
  thing to try. It is a real tradeoff, not a free win: 16384 exists because a
  full book's assembled context was measured at 26,000–30,000 tokens and
  silently overflowed an 8192 window, so the model never saw most of what it
  was asked about. `select_relevant_facts` now caps that, which makes a lower
  value safer than it used to be — but test it rather than assuming.
- **Force the layer count with `$OLLAMA_NUM_GPU`.** Ollama works out how many
  of the model's 28 layers fit and keeps headroom back; when that estimate is
  conservative and a full offload nearly fits, setting the layer count
  explicitly (`OLLAMA_NUM_GPU=28`) can close the gap. Left blank by default,
  deliberately — Ollama decides from the actual free VRAM at load time, which
  bookrag cannot see, so overriding it by default would replace a
  better-informed judgement with a worse one. Asking for more layers than
  genuinely fit fails with an out-of-memory error rather than falling back, so
  raise it in steps. `0` forces CPU.
- **Free VRAM elsewhere.** Browsers and Electron apps hold hundreds of MB;
  another model left loaded in Ollama holds gigabytes (`ollama ps` shows
  everything resident).
- **Use a smaller or more heavily quantized model** — `--model llama3.2:3b`, or
  a `q4` build of the same 7B. This is the *last* resort, not the first: it is
  the only lever here that costs output quality.
- **Close other GPU consumers**, and check the driver: Ollama needs CUDA
  (NVIDIA) or a ROCm-supported AMD card. Most integrated GPUs are unsupported —
  the machine this project is developed on has an AMD Radeon 840M and reports
  `size_vram = 0`, which is why the 5h27m figure above is a CPU number.
- **Use a different machine entirely** without moving your library: point
  `$OLLAMA_BASE_URL` at an Ollama running on a GPU box on your network.

##### The VRAM budget, concretely

For the default `qwen2.5:7b-instruct`, what has to fit is:

| | |
|---|---|
| weights (already `Q4_K_M`) | ~4.7 GB — fixed unless you change model or quantization |
| KV cache | 56 KB per token of `num_ctx` |

So `num_ctx=16384` costs **0.94 GB** of cache on top of the weights (~5.9 GB
total, matching the measured figure above), 8192 costs 0.47 GB, and 4096 costs
0.23 GB. A 6 GB card is borderline at 16384 and comfortable at 8192; 8 GB fits
with room to spare.

Note the model is **already quantized to Q4_K_M** — "quantize it further" is not
the easy win it sounds like, since Q3 and below start visibly degrading output.
The cache is the part worth shrinking. Recent Ollama versions can quantize the
KV cache itself (`OLLAMA_FLASH_ATTENTION=1` plus `OLLAMA_KV_CACHE_TYPE=q8_0`,
set on the **server**, not in bookrag's `.env`), roughly halving those cache
figures without touching the weights at all. Check your Ollama version supports
both before relying on it.

##### Task Manager will lie to you about this

Windows Task Manager's GPU graphs show **3D / Copy / Video Encode / Video
Decode** by default. LLM inference runs on the **Compute** engine, which isn't
one of them — so a GPU doing plenty of work commonly reads **0%**. Click a
graph's dropdown and pick `Compute_0` (and check you're looking at the right
adapter, if the machine has both integrated and discrete).

The reliable signal is **memory, not utilization**: Performance → GPU →
*Dedicated GPU memory* should show several GB in use if layers are offloaded,
regardless of which engine graph you picked. `nvidia-smi` (NVIDIA) or
`rocm-smi` (AMD) report both correctly.

High CPU and high system RAM alongside a partial offload are expected, not
contradictory — the CPU-resident layers are real work, and their weights live
in system RAM. If system memory is near capacity the machine will start paging,
which slows everything down and is its own reason to get the model fully onto
the GPU.

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
- **A single file containing several books is ingested as one long book.**
  An omnibus/bindup (or several books stitched together by hand before
  ingesting) has no boundary detection at all, so its chapters are numbered
  continuously across every book it contains, and repeated "Chapter 1"s are
  just more chapters. `--series`/`--series-position` do not help: they group
  separate *files*, and the stitching already happened. This project's own
  `ranger-s-apprentice-1-2-bindup` is 75 chapters spanning two books. Facts
  and spoiler-scoping are still internally consistent - `--chapter N` means
  the Nth chapter of the *file* - but N no longer corresponds to anything the
  reader sees on the page. Ingest each book as its own file where you can.
  See Future ideas.
- **An answer sometimes lists facts instead of answering the question.**
  `bookrag chat` can return something close to the fact context it was given
  rather than a reply, which is most confusing when two facts genuinely
  conflict (a character wounded in one chapter and well in a later one reads
  as a contradiction rather than as recovery). The facts themselves are
  correct and correctly chapter-scoped; this is an answer-layer problem. See
  Future ideas.
- **Facts can be truncated on dense chapters.** The extraction schema caps a
  chapter at 40 facts (`parsing.py`'s `maxItems`), which exists to make the
  runaway-generation failure structurally impossible - a real incident
  generated 8,490+ output tokens before Ollama's own server gave up. On a
  real 75-chapter run two chapters hit that cap exactly, meaning genuine
  content was cut. Raising it trades the guard against completeness over a
  multi-hour run, so it is a deliberate open decision rather than a knob to
  nudge. Per-chapter fact volume also grows with the known-entities list, so
  the cap binds most in a book's later chapters.
- **Facts extracted before a field existed simply lack it**, and nothing
  backfills them. A book extracted before story-time tracking has no `when`
  on any fact, so its backstory is indistinguishable from its present-tense
  events; a book extracted before provider identities were recorded cannot
  have a resumed run verified against the model that wrote it. Both are
  resolved only by re-extracting that book. When judging library-wide
  behaviour, check *when* each book was extracted before concluding anything
  - a missing field in an old book is evidence about its extraction date.
- **Two distinct occurrences can still be fused into one claim.** The
  recency rule ("a later chapter supersedes an earlier one") is only valid
  for standing attributes, not for events. The real case that exposed it:
  asked "what happened to Halt during the fight with the Kalkara?" (a ch.33-36
  event), the answer pulled in an unrelated ch.66 fact about a separate battle
  and concluded Halt died fighting the Kalkara, which is not what happened -
  two unrelated occurrences that merely shared an entity and a category.
  Answer-layer rendering now separates occurrences from standing attributes
  (see `query.format_context`), which removed the known trigger from real
  data, but the underlying rule is unfixed and there is currently no live
  reproduction of it.
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
- ~~Entity resolution is scoped to the whole library, not to a series~~
  **Resolved.** `resolve_entity` used to match purely on `(name,
  entity_type)` with no check that the books involved were related, so two
  unrelated books that each introduced a same-named, same-typed entity
  silently shared one `entity_id`. This was **not** hypothetical, contrary to
  what this entry claimed for a while: four real cross-book merges were found
  in this project's own library. Identity is now scoped to
  `series_reading_order(book_id)`, and `bookrag doctor --split-cross-book`
  repairs libraries that already merged. Each book's own `facts.jsonl` was
  always correctly scoped regardless, so this was never a spoiler-safety
  issue. The default scope is deliberately the *narrow* one (just the book
  itself): scoping too narrowly duplicates an entity within a series, which is
  visible and repairable by a merge tool, while scoping too widely fuses two
  unrelated characters, which is invisible and cannot be undone by merging.
- ~~No resumable extraction~~ **Resolved (2026-09-09)** - see "Extracting
  facts" above. It is not a multi-version system (running a bigger model later
  without discarding a smaller model's results - see Future ideas), but a
  resumed run *is* now checked against the model that wrote the existing
  facts: `extraction_progress.json` records a provider identity, and resuming
  with a different model is refused rather than silently mixing two models'
  output in one `facts.jsonl`. A book extracted before identities were
  recorded still resumes - unknown means unverifiable, not mismatched.

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
- **A planning pass on multi-book libraries, once several books have been
  re-extracted under current code.** The library has held four books for a
  while, but only one of them was extracted recently enough to carry the
  current fact shape, so there is no way today to tell a real multi-book
  problem from one book simply being older than a feature. Once two or three
  books are comparable, the questions worth working through are: whether
  entity identity behaves across a genuine multi-book series as opposed to
  across unrelated books (four wrong cross-book merges were found and
  repaired once - see `bookrag doctor --split-cross-book`), whether
  `series_reading_order` seeding holds up over a real series, and whether
  retrieval and context size stay bounded as the registry spans more books.
- **Multiple fact-library "versions" per book, keyed by which model
  produced them.** Today, extracting a book a second time with a different
  provider/model overwrites the first run's facts (`--restart`); resuming
  into them is now refused outright rather than silently mixing two models'
  output (see `extraction_progress.json`'s recorded `provider`). Either way
  there's still no way to run a fast local model now and a bigger/better
  model later without losing the first result. The idea: keep both, default reads
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
- **A timeline construct tracking major events, biased toward ones that
  involve the cast** - raised as a real fix for the cross-event conflation
  bug above (see Known limitations), not just a nice-to-have. Root cause of
  that bug: today's facts attribute each statement to exactly one entity
  and one category, with no first-class notion of "a distinct event" - so
  two unrelated occurrences that happen to share a category and entity
  (Halt wounded by the Kalkara in ch.34; a different, unrelated death
  reported in ch.66) look identical to a "trust the later chapter" recency
  rule. A timeline would need multi-entity association per event (the
  current single-`entity_name`-per-fact schema can't represent "Halt was
  struck by the Kalkara" as one event involving both), either as a new
  event construct or a separate `timeline.jsonl` alongside the existing
  per-entity facts. Not self-contained to extraction alone -
  `select_relevant_facts`/the answer prompt would also need to become
  timeline-aware to actually pick the right event for a question rather
  than just the facts. Needs its own planning pass before building.

- **Surface how a thing changed, instead of silently resolving it.** Today
  `ANSWER_SYSTEM_PROMPT` resolves two conflicting same-category facts by
  trusting the later chapter, which throws away the more interesting half of
  the information. Showing the progression instead - "ch.34 wounded and
  unconscious, ch.35 recuperating, ch.36 back on his feet at the ceremony" -
  turns a conflict-resolution rule into a genuine reading-companion feature:
  the reader sees the state evolve across exactly the span they've read. It
  also sidesteps the failure mode where recency silently picks wrong (see the
  cross-event conflation limitation above), since an explicitly-presented
  progression isn't a wrong answer even when the underlying facts disagree.
  Wants the timeline work below to land first, so "progression" can mean
  ordered events rather than same-category facts that merely share an entity.
- **Facts record only what is true, never what is absent.** Reported from
  real use: in *The Magic Thief*, magisters carry a stone called a locus
  magicalicus. Asked what a magister's stone looks like, `chat` answers well.
  Asked what a *non*-magister's stone looks like, it says "I don't have
  enough information" - honest, not a hallucination, but the correct answer
  is **"he doesn't have one."** Same shape as asking what Horace's cloak
  looks like: he has none, because he isn't a Ranger. There are two separate
  problems hiding here, and they differ enormously in cost:
  - **Stated absence** - the text literally says someone lacks something.
    Extraction can capture this today; it needs a polarity notion on a fact
    (or a category) so "has no cloak" doesn't render as a cloak fact. Cheap,
    and worth doing first.
  - **Inferred absence** - nothing states it; it follows from a class rule
    ("only Rangers wear that cloak") plus a membership fact ("Horace is a
    Battleschool apprentice"). This is the hard half, and the reported
    framing - per-book "important details" identified at ingest or during
    the first few chapters - is one way, but probably not the cheapest.
    Worth testing first: the catalog may already hold both halves as
    ordinary facts, and the gap may be that `select_relevant_facts` never
    retrieves the *class-level* entity alongside the character, so the model
    is never given the rule it would need to reason from. If so this is a
    retrieval + prompt change rather than a new extraction construct. Needs
    a planning pass, starting with that experiment.
- **A single file containing several books ("omnibus"/"bindup") is treated
  as one long book.** Reported from real use: a 5-book epub, stitched
  together before ingestion, so the text contains five separate "Chapter 1"s.
  `--series`/`--series-position` do not help - they group *separate files*,
  and by ingest time the stitching has already happened. This project's own
  library has the same shape (`ranger-s-apprentice-1-2-bindup`: 75 chapters
  spanning two books). Consequences are real, not cosmetic: `--chapter 40`
  means nothing to a reader who is on chapter 6 of book 3, spoiler scoping is
  coarser than it looks, and any future citation feature is unusable until
  this is solved. Design questions: detect the boundaries at ingest (a
  repeated title pattern, a restarting chapter numbering, a title-page
  signal) or offer an explicit `--split-at` flag; then decide whether to
  write N separate `book_id`s wired together with the existing series
  metadata (reuses everything, costs a re-ingest) or keep one book with a
  sub-book field on each chapter (cheaper, but every consumer of
  `chapter_index` has to learn about it). The first is probably right,
  because it makes the rest of the system need no changes at all.
- **Nicknames and alternate names for one character.** Reported from real
  use: *The Magic Thief*'s protagonist appears as Conn, Connwaer, "the boy"
  and "bird", and facts scattered across all of them. Note this is **not a
  greenfield feature** - `entities.json` already carries an `aliases` list on
  every entity, `extract.resolve.resolve_entity` already matches against it,
  and `query.select_relevant_facts` already searches it. What's missing is
  anything that *populates* it from the text: only 2 of 493 entities in the
  real library have an alias, and both came from
  `bookrag doctor --merge-duplicates`, not from reading a book. So the
  question is narrower than it first appears - where does alias detection
  run (an extraction-time field, a separate cheap pass over chapters, or a
  `doctor`-style offline pass over existing facts), and how is a false merge
  avoided, since wrongly fusing two characters is invisible and hard to undo
  (the same asymmetry that made `resolve_entity`'s scope deliberately
  narrow). An epithet like "the boy" is also chapter-scoped in a way a real
  name isn't - it may refer to someone else entirely later.
- **Book-level facts: protagonist, antagonist, cast, main plotline.**
  Requested as a way to ask "who is in this book?" without naming anyone
  first. Today every fact hangs off one entity and there is no book-level
  layer at all (`metadata.json` holds only bibliographic fields). **This is
  the most spoiler-dangerous idea on this list and must not be built before
  the spoiler-safety tests below.** "Antagonist" and "main plotline" are
  close to a definition of what spoils a book: a cast list rendered at
  chapter 3 that names the chapter-60 villain is a leak, and so is an
  antagonist field that is populated at all before the reader meets them.
  Anything here has to be chapter-scoped exactly like `facts_as_of`, which
  means it is derived per-query, not stored once at extraction time. Some of
  it is also nearly free without a model: "protagonist" is well approximated
  by the most-referenced character so far, and "cast" by the entity list
  already filtered to the current chapter. Worth separating the cheap
  derived half from the genuinely model-authored half (plotline) before
  designing.
- **Citations back to where a fact came from.** Requested so a reader can
  open their own copy and find the passage - e.g. a physical description of
  a character, traced to the page that states it. Facts already carry
  `chapter_index`, so the coarse version exists; what's missing is anything
  finer, and the finer version is harder than it looks. `extract_book` passes
  whole chapter text to the model and stores only the returned statement - no
  character offset, no sentence anchor - so locating the source text again
  means either re-finding it after the fact (fuzzy match of the statement
  back against the chapter, cheap and approximate) or capturing an offset at
  extraction time (exact, but a schema change, and a small local model
  quoting offsets reliably is an open question). Two things also degrade the
  output regardless of mechanism: a `text-bound` book's "chapters" are
  self-created fragments a human cannot find in a printed copy, and a
  stitched omnibus (above) makes even a correct chapter number meaningless.
  Fuzzy-matching the statement back to a sentence, then reporting
  "chapter N, about 60% through", is likely the best available answer for
  those books and should be designed for explicitly rather than treated as a
  degraded case.
- **Answers that read as answers, not as a list of facts.** Reported from
  real use: `chat` sometimes returns what is effectively the fact dump it was
  given rather than a reply to the question. This is partly a prompt problem
  and partly a missing feature, and the two halves want splitting:
  - **The reply should be prose by default.** Cheap: an answer-prompt change,
    measurable the same way the Background-leak fix was (see
    `context/src/bookrag/providers/prompts.py.md`).
  - **Seeing the underlying facts should be opt-in, not accidental** - a
    flag, or a marker in the question, that appends the facts actually used.
    This is genuinely useful for checking an answer, which is why the
    behaviour shouldn't just be suppressed.
  - **Conflicting facts confuse a reader precisely because they arrive
    without a narrative.** The reported example is the existing Halt/Kalkara
    case: wounded in one chapter, well in a later one, presented as a flat
    contradiction rather than as recovery over time. The reported intuition
    is right - `when`/`time_phrase` already exist to carry exactly that
    ordering - but the durable fix is the timeline construct above, not more
    prompt text, and this is the same defect as the cross-event conflation
    limitation. Do the cheap prose fix now; do this part with the timeline.
- **Configurable cross-category answer eagerness.** `ANSWER_SYSTEM_PROMPT`
  tells the model to read across *all* of an entity's categories rather than
  only the one whose name matches the question, which is what lets "what does
  Halt look like?" pick up a physical detail filed under `personality`. In
  practice it also pulls in a character's carried equipment (a knife, a bow)
  for a physical-description question - **intended behaviour**, since what
  someone carries is part of how they appear. Noted here only in case a future
  case proves it *too* eager for some question shapes, at which point the
  breadth would want to be a setting rather than a fixed instruction. Not a
  defect today, and nothing to fix unless a real over-reach shows up.

## For future development sessions (Claude or human)

This project keeps a **mirrored context doc** under `context/<path>.md` for
every file under `src/` and `tests/`, summarizing purpose/interface/decisions
so you don't have to re-read full source just to know what a file does. This is
hook-enforced for `src/` and for `.py` files under `tests/`: a Claude Code
`Stop` hook blocks ending a turn while any touched file's context doc is out of
sync, and a `SessionStart` hook catches edits made outside the editor tools.
`python install.py` runs the same check for anyone not using Claude Code. See
`CLAUDE.md` for the full convention and template before editing source.

`tests/` was originally detected-but-not-blocked, and eleven test docs drifted
before anyone noticed — one of them still describing entity behaviour that had
been removed. Adding a test counts as a change that needs its doc updated.
