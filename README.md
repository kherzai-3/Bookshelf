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

  **Don't pick a model on speed — measure it.** A real, controlled
  comparison on this project's own data, six chapters of one book, same
  prompt and schema, CPU-only:

  | | `qwen2.5:7b-instruct` | `llama3.2:3b` |
  |---|---|---|
  | wall-clock per chapter | 205s | **168s** |
  | facts | 94 | 195 |
  | **distinct entities** | **25** | **16** |
  | **near-duplicate statement pairs** | **4** | **53** |
  | chapters at the 40-fact ceiling | 0 of 6 | **3 of 6** |
  | groundedness | 0.884 | 0.851 |
  | citation coverage | 77% | 75% |

  The smaller model *is* faster, and it wins on the two numbers you would
  naively look at — more facts, less time. It is still the worse choice:
  those facts cover 36% fewer entities, thirteen times as many are
  near-duplicates of each other, and it hit the output ceiling in half the
  chapters. On one chapter it returned 40 facts about a *single* character,
  missing three others the same 970 words introduce. That is padding, not
  richer extraction.

  - **`qwen2.5:7b-instruct` (the default)** - more selective and more
    accurate on the same text, and the same comparison found `llama3.2:3b`
    also asserting things the chapter does not say. Expect a few minutes per
    chapter, i.e. multiple hours for a full novel, whether or not a GPU is
    available. `bookrag extract` is [resumable](#extracting-facts)
    specifically because of this.
  - **On more constrained hardware**, fall back to a smaller model (e.g.
    `llama3.2:3b`) via `--model llama3.2:3b` / `$OLLAMA_MODEL` - it runs in
    less RAM/VRAM, at the cost measured above. Confirm any model choice
    empirically before committing to a full-book run: `bookrag eval` is
    fast (a chapter or two, not the whole book) and read-only, never
    touching `facts.jsonl`/`entities.json`. **`--models` compares candidates
    head to head in one command**, which `--model` cannot do — it applies a
    single model to every provider listed:

    ```bash
    bookrag eval <book-id> --chapters 6,7 --models qwen2.5:7b-instruct,llama3.2:3b
    ```

    It reports exactly the table above: distinct entities, citation
    coverage, near-duplicate pairs, how often the fact ceiling was hit,
    groundedness, and real cost in both seconds and tokens. See
    [Comparing models before you commit](#comparing-models-before-you-commit)
    for the full output and how to read it.

    Switching models for a book you have already extracted means
    re-extracting it from chapter 0 — `bookrag extract` refuses to append
    one model's facts to another's, and `--restart` is the only way past
    that. Measure first.
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
bookrag ingest "path/to/some-book.epub"   # quote it - see Ingesting a book
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
mv ~/Downloads/"Some Book.epub" data/incoming/
```

(the `~` stays *outside* the quotes - inside them it's a literal `~`, not your
home directory)

```bash
bookrag ingest "data/incoming/Some Book.epub"
bookrag ingest "path/to/book.pdf" --title "Custom Title" --author "Someone"

# books in a series: chapters are always scoped per-book, so two books can
# each have their own "chapter 2" without collision. --series-position is
# required whenever --series is given.
bookrag ingest "book1.epub" --series "The Saga" --series-position 1
bookrag ingest "book2.epub" --series "The Saga" --series-position 2

# self-help, philosophy, or other non-narrative books - selects a different
# category/entity taxonomy for extraction (see below). Defaults to
# "fiction" - not auto-detected, so this must be passed explicitly.
bookrag ingest "atomic-habits.epub" --content-type nonfiction

# an omnibus/bindup is ingested as one book, with the volumes inside it
# detected and used to label citations (see below). Nothing to pass.
bookrag ingest "ranger-s-apprentice-1-2-bindup.epub"
```

**Quote the path.** Book filenames routinely contain spaces and apostrophes,
and an unquoted apostrophe is the worse of the two: in PowerShell it opens a
string literal that never closes, so the command is never run at all. You get
a `>>` continuation prompt and something that looks exactly like a hung
ingest - but nothing has started, which is why `ollama ps` shows nothing
either. Ctrl+C, then re-run with double quotes:

```bash
bookrag ingest "data/incoming/Ranger's Apprentice.epub"
```

Dragging the file from Explorer (or Finder) into the terminal pastes the path
already quoted, which is the easiest way to never think about this again. For
reference, a real ingest takes about a second, even for a 70 MB file - if it
is still going after ten, something other than parsing is wrong.

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

#### Naming the books inside an omnibus, automatically

A bindup, a "complete collection" or a fan-compiled series file holds several
separately-published books end to end. Ingested naively, it becomes one book
with five "Chapter 1"s, and every chapter number the tool reports afterwards
is one the reader cannot find in their own copy.

Ingest detects the volumes from the file's own table of contents and records
where each one starts and ends. The file stays **one book** — chapter numbers
are unchanged — and citations name the volume instead of the file:

```
Ingested 'The Magic Thief Complete Collection: Books 1-5' as
'the-magic-thief-complete-collection-books-1-5' (84 chapters)

Volumes:
  This file holds 5 separately published books (99.9% of its text falls inside them).
  Ingested as one book - chapter numbers are unchanged - but a citation
  will name the volume and count chapters from its start, so it points at
  something a reader can find:
    The Magic Thief -> The Magic Thief
    The Magic Thief: Lost -> The Magic Thief: Lost
    ...
```

So a fact from chapter 46 of the file is cited as *"The Burning Bridge,
Chapter Fourteen"*, and one from chapter 1847 of a 24-volume webnovel as
*"Reverend Insanity Volume 12, Chapter 1187"*. `bookrag show <book_id>` lists
the volumes and their chapter ranges if you want to check what it decided.

**It refuses far more often than it fires**, deliberately: inventing volumes
in a book that has none puts a wrong book title on a citation, silently. A
candidate set must not overlap, must hold at least 85% of the file's text,
and each volume must be at least 1,000 words. Measured over the eight books
in the development library:

| book | nested TOC sections | verdict |
| --- | --- | --- |
| Ranger's Apprentice 1 & 2 Bindup | 2 | 2 volumes — 98.4% coverage |
| The Magic Thief Complete Collection | 5 | 5 volumes — 99.9% coverage |
| Reverend Insanity (24 volumes) | 24 | 24 volumes — 100% coverage |
| Moby Dick (Project Gutenberg) | 5 | **no volumes** — sections overlap, 45.2% coverage |
| The Eye of the World, The Perfect Run, Atomic Habits | 0 | no volumes |

Moby Dick is the case that sets the guards: its five nested sections
("ETYMOLOGY.", "CHAPTER 100. Leg and Arm.", "Epilogue", …) are typesetting
artifacts pointing into a single document, not volumes.

> **This used to split the file into one book per volume, and no longer
> does.** The split produced the same citation string and charged a lot for
> it: every chapter outside a volume was deleted, it needed a `--no-split`
> flag to escape, and the source file was archived once and shared by a
> back-reference between books. A citation is a *rendered* location — what
> the database keys a chapter as never mattered.

Limits worth knowing:
- **epub only.** A PDF outline can nest too, but `pdf_loader` flattens it to
  level 1, so the nesting is gone before the detector sees it.
- **Detected at ingest**, so books already in your library gain volume labels
  only when you re-ingest them.
- Nothing groups the volumes as a series. When a bindup was split into
  separate books that mattered, because extraction seeds each book with the
  previous books' characters; one book has no such seam to bridge.

#### Linking a narrator's names, automatically

If the book has a **first-person narrator**, ingest reads how other
characters address them and links the names it finds into one character
before extraction ever runs, printing what it did:

```
'Conn' also answers to Connwaer
  and is referred to as boy, lad, thief, shadow, blackbird, cousin
  Wrong? `bookrag aliases <book-id> --unlink` undoes it, before or after extraction.
```

This matters because it happens *before* extraction: an entity that already
carries the aliases absorbs every later mention, so the character is never
split in the first place. Names and terms of address are kept in two
separate lists - a name reaches both entity resolution and question
matching, an epithet reaches only entity resolution, so "boy" can collect a
fact filed under "boy" without making every question containing that word
retrieve this character.

**It fires in one narrow case, and stays silent otherwise** - which is the
correct answer for most books, but worth knowing so its silence isn't read
as a failure:

- **First person only.** A third-person book has no narrator to address, so
  this detector finds nothing. That is not the end of the story any more: a
  *second* linker runs at the same moment and does work on third-person
  books, grouping a character's titled names ("Magister Nevery" with
  "Nevery"). See "Titles and other forms of a character's name" below.
- **Two or more spellings of a name are required.** Detection needs two
  independent signals, and one of them is a string relationship between two
  names - so a narrator with a single name links nothing. Most first-person
  narrators have one name.
- **Speaker attribution only reads single-token names.** The attribution
  pattern matches one capitalised word, so a book whose characters have
  multi-token names ("Fang Yuan", "Mrs Hudson") yields no attributable
  speakers and therefore no detections at all. Measured, not theorised - see
  `context/src/bookrag/ingest/vocatives.py.md`.

`bookrag aliases <book-id>` shows what was found and what was linked.

### Titles and other forms of a character's name

Also automatic, also at ingest, and it works on third-person books - where
the narrator detector above has nothing to say. If a book calls someone both
"Nevery" and "Magister Nevery", those become one character before extraction
starts, so their facts never split in the first place.

```
Linked:
  'Nevery' also answers to Magister Nevery
  'Rowan' also answers to Duchess Rowan, Lady Rowan
  'Crowe' also answers to Underlord Crowe
```

**No list of titles is involved**, which matters for books that invent their
own. "Magister", "Underlord" and the Chinese clan prefix "Gu Yue" are not in
any honorifics list and could not be - the book made them up. Instead of
asking "is this word a rank?", the rule asks whether what is *left* after
removing it is a name the book uses far more often on its own: "Nevery"
appears 1,536 times and "Magister Nevery" 20, so the longer form is a
decoration of the shorter.

Two things keep it from merging a thing into a person. A real name is almost
never preceded by "the" or "a" - nobody writes "the Fang Yuan" - and a
character is caught speaking ("Nevery said"). A category fails the first test
and a place fails the second.

On a long book this adds a minute or two to ingest, which it says before it
starts. It is the cheapest possible moment to spend that time: the
alternative is discovering the split after a multi-hour extraction.

`bookrag aliases <book-id>` lists every group with the reason it was linked,
and `bookrag aliases <book-id> --unlink` undoes all of them. `bookrag ingest
--no-auto-link` skips both linkers entirely.

**Known limits**, all measured across the eight books this was built on
(124 links, one wrong):

- **A thing named after a person still merges into them.** "Mount Augustus"
  links to "Augustus", who is a real character in that book. No test of the
  text can separate those, because grammatically they are identical; the
  entity types available after extraction can, which is why
  `doctor --merge-name-variants` is stricter.
- **Sentence-initial words get linked, harmlessly.** In a long book the
  protagonist collects forms like "But Fang Yuan" and "And Fang Yuan". Those
  are correct - they *are* that character - and they cost nothing, because a
  question only matches an alias if the whole alias appears in it. Ingest
  reports a count rather than listing them.
- **An organisation or a place occasionally slips through**, if the book
  writes its name bare and has its members speak. "Heavenly Court" is the
  real example.
`--unlink` undoes it, but note that undoing it *after* extraction means the
facts already carry the merged `entity_id`: a genuine undo needs
`--unlink` plus `extract --restart`, which is a full re-extraction.

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

- **Extraction already does this for you.** `bookrag extract` sizes its
  context window from the book's own longest chapter and prints what it
  chose:

  ```
  Extracting 'ranger-s-apprentice-1-2-bindup' - 75 chapter(s) via ollama:qwen2.5:7b-instruct
    context window sized to 8192 tokens from this book's longest chapter
  ```

  Measured across this project's corpus, most books land at 8192 rather than
  16384 — about 0.9 GB of KV cache saved with nothing given up, because their
  chapters never needed the larger window. Books with genuinely long chapters
  (*The Eye of the World* has 43 over 8,192 tokens, its longest at 15,736)
  correctly keep 16384, which is why this is computed per book instead of
  just being a smaller default. `$OLLAMA_EXTRACT_NUM_CTX` sets a **ceiling**
  if you want to force something smaller still; extraction only ever goes
  below it.

- **Lower `$OLLAMA_NUM_CTX`.** This sizes the KV cache for `bookrag chat`
  (extraction has its own setting, above). Measured on a 7B model: **5.94 GB
  at `num_ctx=16384`** (the default) versus **5.06 GB at 4096** — so nearly a
  gigabyte of VRAM. It is a real tradeoff, not a free win: 16384 exists
  because a full book's assembled context was measured at 26,000–30,000
  tokens and silently overflowed an 8192 window, so the model never saw most
  of what it was asked about. `select_relevant_facts` now caps that, which
  makes a lower value safer than it used to be — but test it rather than
  assuming.
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
- **Quantize the KV cache** — `OLLAMA_FLASH_ATTENTION=1` plus
  `OLLAMA_KV_CACHE_TYPE=q8_0`, on the **server**. Measured at **5.9 → 5.5 GB**
  with no detectable quality cost, but **2× slower prefill on CPU**; on a GPU
  that penalty likely does not transfer. See the budget section below.
- **Use a smaller or more heavily quantized model** — `--model llama3.2:3b`, or
  a `q3` build of the same 7B. This is the *last* resort, not the first, and
  the measurements below show why: it is the only lever that costs output
  quality, and on this machine the `q3` build was **slower as well as worse**.
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

Note the model is **already quantized to Q4_K_M** — and "quantize it further" is
not the easy win it sounds like. Measured here, `qwen2.5:7b-instruct-q3_K_M`
against the Q4_K_M default on the same two real chapters, CPU-only:

| | Q4_K_M | q3_K_M |
|---|---|---|
| resident at `num_ctx=16384` | 5.9 GB | **5.1 GB** |
| seconds per chapter | **245s** | **329s (+34%)** |
| prompt eval | 143s | **321s (2.2×)** |
| citation coverage | **71%** | 64% |
| groundedness | **0.92** | 0.87 |
| distinct entities | 15 | 14 |

So Q3 is **slower as well as slightly worse** — Q3_K dequantisation costs more
arithmetic per weight than Q4_K_M, which is the most-optimised path, and on CPU
that outweighs having fewer bytes to read. It buys 0.8 GB for 7 points of
citation coverage. On a GPU the speed result may invert if the card is
bandwidth-bound; the quality result will not. **The cache is the part worth
shrinking.**

###### Quantizing the KV cache — measured, and it is not free on CPU

`OLLAMA_FLASH_ATTENTION=1` plus `OLLAMA_KV_CACHE_TYPE=q8_0` (set on the Ollama
**server**, then restart it) stores the cache at 8 bits instead of 16. Measured
here on the same two chapters, against an f16 baseline:

| | f16 KV | q8_0 KV |
|---|---|---|
| resident at `num_ctx=16384` | 5.9 GB | **5.5 GB** |
| **prompt eval** (~7,860 tokens both) | 143s | **283s — 2.0×** |
| seconds per chapter | 245s | 337s (+37%) |
| citation coverage | 71% | 88% |
| groundedness | 0.92 | 0.94 |
| distinct entities | 15 | 15 |

**Quality showed no degradation** — notably `distinct entities` was identical,
which is the metric most at risk, since `resolve_entity` matches names exactly
and a single corrupted proper noun mints a duplicate character. Do not read the
coverage jump as an improvement though: at n=2 chapters and temperature 0.2 the
run-to-run spread is wider than that difference.

**But it cost 2× on prefill**, measured by Ollama's own timer rather than
wall-clock, so contention cannot explain it: a quantized cache must be
dequantized on every attention operation, and on CPU that arithmetic outweighs
the bandwidth saved. **On a GPU this penalty likely does not transfer** — a card
is bandwidth-bound and has efficient quantized-KV kernels — and if it is what
takes you from a partial offload to a full one, that is worth far more than any
prefill cost. Measure it on your own card rather than assuming either way. Recent Ollama versions can quantize the
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

Before committing to a run this long, see **[Comparing models](#comparing-models-before-you-commit)**
below — changing model afterwards means re-extracting the book from chapter 0.

### Comparing models before you commit

`bookrag eval` runs one or more models over the same chapters and reports how
they did. It is **read-only** — it never writes to `facts.jsonl` or
`entities.json`, so it is safe against a real library.

```bash
# Compare two models of the same provider - the usual case
bookrag eval <book-id> --chapters 6,7 --models qwen2.5:7b-instruct,llama3.2:3b

# Compare providers instead (a single model applied to each)
bookrag eval <book-id> --chapters 0,1,2 --providers ollama,fake

# One model, just to see what extraction looks like on this book
bookrag eval <book-id> --chapters 0,1,2
```

`--models` is the one to reach for. `--model` sets a single override applied to
*every* provider listed, so it cannot compare two models of one provider;
`--models` takes the cross-product with `--providers` and labels each row
`provider:model`. Only pulled models work — check with `ollama list`.

Output looks like this:

```
[ollama:qwen2.5:7b-instruct] 41 facts across 2 chapter(s), 0 parse failure(s), avg groundedness 0.92
  quality: 15 distinct entities, 71% citable, 1 near-duplicate pair(s), 0/2 chapter(s) at the 40-fact ceiling
  cost: 489s total, 245s/chapter, 1967 output tokens, 7864 prompt tokens (143s to evaluate)
  ch6: Martin was secretary to Baron Arald. | Alyss was a castle ward.
```

**How to read it.** Fact count and speed are the two numbers that will mislead
you — on a real comparison the smaller model produced twice the facts 18%
faster and was still clearly the wrong choice. The quality line is what
actually separates models:

- **distinct entities** — how many different characters/settings/themes it
  found. A model producing many facts about few entities is padding.
- **citable** — the share of statements the passage matcher can locate in the
  chapter, i.e. how well [citations](#chatting-with-a-book) will work. A model
  that paraphrases further from the prose costs you this silently.
- **near-duplicate pair(s)** — statements that say the same thing in different
  words. The pipeline's dedup only catches *exact* repeats, so these survive
  into your library and inflate the fact count.
- **N/M chapter(s) at the ceiling** — chapters that hit the schema's 40-fact
  cap. That is never a healthy result: either truncation or padding.
- **cost** — prompt tokens are reported alongside the seconds it actually took
  to evaluate them, because Ollama caches a repeated prompt prefix and the two
  numbers disagree wildly (an identical prompt measured 34.23s cold, 0.12s
  warm). Trust the seconds.

Groundedness is a cheap lexical check — do a fact's key words appear in the
chapter text — not a semantic judge.

Two chapters is usually enough to separate two clearly different models, and
takes a few minutes rather than the hours a full book costs.

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

#### Where an answer came from

Every answer is followed by a **Sources** block saying where in your own copy
each fact came from:

```
Sources:
  The Ruins of Gorlan, Chapter Three, 66% in - "Will had never heard Halt speak before."
  The Ruins of Gorlan, Chapter Two, 72% in - "He looked up and actually started with surprise as he
  met the dark, unfathomable gaze of Halt, the Ranger."
  Finite and Infinite Games, pp. 79-85 - "A finite game is played for the purpose of winning."
```

**The quote is the part that actually finds the passage.** A chapter number
belongs to one printing and a page number to one scan, but a sentence belongs
to the book — you can search for it in any reader, any edition, any format.
The label before it is orientation.

bookrag writes these itself rather than asking the model to cite its sources,
because a small local model asked for a citation will invent one, and a
citation that might be fabricated is worse than none. Every source line is
computed from the library, so it is either correct or absent.

The label is the best thing your book actually offers, in this order:

1. **A page range** (`pp. 79-85`) when the source has real pagination — a PDF,
   or a page-scanned epub. Preferred over a chapter title, because a book can
   have a title for every chapter and have all of them be useless: every
   chapter of *Finite and Infinite Games* is titled, and they are all PDF
   bookmark IDs like `FAIG0080`.
2. **The book's own chapter name** (`Chapter Three`, `CHAPTER 100. Leg and
   Arm.`) — read from the epub's table of contents when the chapter text
   itself has no heading, which is how most books get one.
3. **`chapter N`**, the bare index, when the book offers nothing else.

Inside an omnibus the volume is named, not the file — "The Burning Bridge,
Chapter Fourteen", never "Ranger's Apprentice 1 & 2 Bindup, chapter 48" — and
an untitled chapter is counted from the volume's own start, not the file's.
See [Naming the books inside an
omnibus](#naming-the-books-inside-an-omnibus-automatically).

**A quote is shown only when the match is confident.** A citation pointing at
the wrong sentence tells you the book says something it does not, and you
would have no way to tell it apart from a correct one — so when the match is
weak you get the location and no quote.

Measured by hand-scoring **181 statements** from eleven chapters of six
books, produced by the default model (`qwen2.5:7b-instruct`):

| book | statements | quoted | correct |
| --- | --- | --- | --- |
| Moby Dick | 19 | 19 | 18 — 95% |
| Atomic Habits | 37 | 27 | 26 — 96% |
| The Perfect Run | 42 | 33 | 31 — 94% |
| The Magic Thief | 27 | 14 | 13 — 93% |
| Ranger's Apprentice | 42 | 37 | 30 — 81% |
| The Eye of the World | 14 | 0 | — |
| **all six** | **181** | **130 (72%)** | **118 — 91%** |

**Coverage varies enormously and precision barely does.** Whether a chapter
gets quotes at all turns out to depend on how much of the model's *own*
vocabulary appears nowhere in the chapter: across the eleven chapters that
share predicts the match score at r = −0.81. The Eye of the World chapter is
the extreme — a third of the model's words are absent from the chapter,
because it summarises interior states ("Rand was feeling paranoid and on
edge") that no sentence in the book states, and not one of its 14 statements
clears the bar. Abstaining there is the right answer, but it means coverage
is a property of the chapter, not a dial.

**The confidence threshold is worth very little**, which the same
measurement settled. Moving it from 0.30 to 0.70 changes precision by six
points and coverage by forty-one. It stays at 0.40 because a wrong quote
costs more than a missing one, not because 0.40 is tuned.

**The errors that remain are not the kind a threshold catches.** The three
worst-scoring mistakes score 1.00, 0.98 and 0.98 — and in all three the
*statement* is wrong while the matcher correctly found the sentence the
model misread. The rest are near misses, where one rare word carries the
match: four statements like "Gilan inspected the garrison house" all landed
on "He inspected the tip of his finger."

Citations never read any chapter but the one a fact came from, and never
show anything derived from the whole book (no "chapter 12 of 75", no
percentage through the *book*) — both would leak. This is covered by the
spoiler-safety gate, not just by intention; see
[The spoiler-safety gate](#the-spoiler-safety-gate).

### Managing your library

```bash
bookrag list                    # every book: chapters, content type, extraction status, series
bookrag show <book-id>          # full detail for one book, including entity count

bookrag remove <book-id>        # asks for confirmation, then deletes the book + its facts
bookrag remove <book-id> --yes  # skip the confirmation prompt

bookrag aliases <book-id>       # show the names a book uses for its narrator
bookrag aliases <book-id> --auto        # link them into one character
bookrag aliases <book-id> --link A,B    # link two names by hand
bookrag aliases <book-id> --unlink      # undo a link (see the caveat below)

bookrag doctor                  # read-only consistency check
bookrag doctor --fix            # apply the safe, obvious cleanups it finds
bookrag doctor --merge-name-variants   # merge "Baron Arald" and "Arald" into one person
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

`doctor` also reports three things `--fix` deliberately never touches,
because each one picks a winner and permanently rewrites which entity owns a
fact — a judgment call, not a cleanup. Each has its own opt-in flag:
`--merge-duplicates` (the same name spelled differently),
`--split-cross-book` (two unrelated books' characters fused into one), and
`--merge-name-variants` (below).

**One character under several names.** If a book calls someone both "Baron
Arald" and "Arald", they end up as two entities with their facts split
between them, and a question about one finds only half the story.
`--merge-name-variants` finds these and offers them one at a time, with the
evidence shown before the question:

```
2 entities that look like one name under several forms:
  - Baron Arald (39 facts), Arald (10 facts)
      same name with and without a title or rank (in ranger-s-apprentice-1-2-bindup)
```

Merging records every other spelling as an **alias**, which is what makes a
question about any of them find all the facts. Three kinds of evidence count,
and nothing is proposed without one of them:

- a rank in front of a name — "Baron Arald" and "Arald";
- a given name and a fuller form — "Alyss" and "Alyss Mainwaring";
- the book saying so itself — "Connwaer, but everyone called him Conn".

It is deliberately cautious, and it stays silent rather than guessing. A name
inside *two* longer ones (two characters sharing a given name) is refused
outright, because a wrong merge is invisible and cannot be undone by merging
again. Similar spelling alone is never enough: "Skandia" and "Skandians" are
a place and its people, and nothing but the book's own words will link two
names that merely start alike.

That caution has a measured cost, and it falls hardest on the characters
that need this most: a character with several titles sits inside several
longer forms of their *own* name, which the rule cannot tell apart from two
people sharing a given name, so it refuses. See Known limitations - this is
known-wrong rather than merely conservative, and the fix is planned.

`bookrag aliases` is the other half of this, and works from the opposite
signal - who addresses whom, rather than what names look like. It applies
only to first-person narrators and normally runs by itself at ingest; see
"Linking a narrator's names, automatically".

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

### The spoiler-safety gate

`tests/test_spoiler_safety.py` is not an ordinary test module. Everything else
here exists so that an answer about chapter N is safe for someone who has only
read to chapter N, and these are the tests that say it actually is. They run
the whole real path a `bookrag chat` turn runs, because a leak is far more
often an interaction *between* the query steps than a bug inside one of them.

Two of them carry the guarantee, and they fail for different reasons:

- **The sentinel test** gives every chapter a token that appears nowhere else,
  then checks every reading position against every retrieval path. When it
  fails it tells you exactly which chapter escaped into which render.
- **The truncated-library equivalence test** renders chapter N twice - once
  from a library holding the whole book, once from a library that never held
  anything past chapter N - and requires the two to be byte-identical. It has
  no idea what a leak looks like, which is why it catches the kinds a sentinel
  cannot: a count in a header, a relevance score computed over facts the reader
  hasn't reached, an ordering that shifts once a later chapter exists.

Both were sabotage-verified, and the second sabotage is the reason both exist:
making the render leak a *number* derived from the whole book - copying no text
at all - leaves the sentinel test passing and fails equivalence everywhere.

**If you add a new way to render facts to a reader, extend these.** Equivalence
only guards what it is pointed at.

## Known limitations

- **`bookrag remove` deletes your copy of the book, and doesn't say so.**
  Open, and the most damaging item on this list. `ingest` effectively *moves*
  a staged file: it copies into `data/library/<book_id>/source.epub` and then
  deletes the original from `data/incoming/`. The library copy is therefore
  the only copy. `remove` then deletes the whole directory, warning only that
  "this deletes its chapters/facts permanently" — it never mentions the book
  itself. So ingest-then-remove silently destroys the user's file, having
  warned them about the wrong thing. Found the hard way during development,
  on a book that had to be re-downloaded. Four options, not yet chosen:
  1. **Warn accurately.** Name `source.epub` in `remove`'s prompt and say the
     book file goes with it. Cheapest, changes no behaviour, and still loses
     the file for anyone who types `--yes`.
  2. **Restore on remove.** Move `source.*` back to `data/incoming/` instead of
     deleting it. The book survives, the library ends up clean, and the file
     lands where the user originally put it. Slightly surprising if they
     expected `remove` to remove things.
  3. **Copy at ingest, don't move.** Leave the staged file alone. Safest, but
     it abandons a deliberate convenience (`data/incoming/` stops being a
     staging area and becomes a pile), and duplicates every book on disk.
  4. **`ingest --keep-source`.** Opt-in version of 3. No protection by default,
     which is the case that actually bit.
  2 or 1+2 look best; 2 alone means no prompt has to be read at the moment it
  matters.

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
- ~~A single file containing several books gives chapter numbers a reader
  cannot find in their own copy.~~ **Resolved for epubs whose table of
  contents names the volumes** — ingest records where each volume starts and
  ends, and citations name the volume and count from its start (see [Naming
  the books inside an
  omnibus](#naming-the-books-inside-an-omnibus-automatically)).
  What remains: **a PDF omnibus is not detected**, because
  `pdf_loader` flattens the outline to level 1 before anything can read the
  nesting; and an epub whose volumes are *not* marked in its table of
  contents (books concatenated by hand, or a TOC that lists every chapter
  flat) has no signal to detect and is left whole. For those, ingest each
  book as its own file where you can.
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
  real 75-chapter run two chapters hit that cap exactly. Raising it trades the
  guard against completeness over a multi-hour run, so it is a deliberate
  open decision rather than a knob to nudge. Per-chapter fact volume also
  grows with the known-entities list, so the cap binds most in a book's
  later chapters.

  **Hitting the cap turns out to be a symptom, not just a ceiling.** Across
  eleven sampled chapters exactly one reached 40 facts, and 25 of those 40
  were verbatim repeats of a statement already in the list — 62%, against
  0–6% in every chapter that stopped on its own. What the model does when it
  runs out of things to say is restate its last observation with one detail
  changed ("Nevery was a wizard who had a workroom with a high table…", "…
  with dirty teacups…", "… with a high stool"), until the schema stops it.
  So a capped chapter yields perhaps a third of what its fact count suggests.
  Exact `(entity, statement)` repeats are dropped before anything is stored,
  so the library stays clean; the loss is in yield, and the cap is a usable
  signal that a chapter is worth re-running rather than evidence that it was
  too rich to fit.
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
  output happens to name them consistently. Automatic linking is no longer
  entirely future work: ingest links a first-person narrator's names before
  extraction (see "Linking a narrator's names, automatically"), and `bookrag
  doctor --merge-name-variants` merges name variants afterwards. Neither is
  coreference - both work from names and forms of address, not from a
  descriptive phrase like "the old man", which still links to nothing.
- **A third-person character with many titles or assumed identities stays
  fragmented, and the merge rules get *less* likely to fire the more names
  they have.** Reported from real use on a translated web novel whose
  protagonist appears as "Fang Yuan", "Gu Yue Fang Yuan",
  "Lord/Elder/Demon King Fang Yuan", and nine assumed identities. Measured
  against the real ingested text: the shipped rules link **3 of ~30** surface
  forms, and only because "lord" happens to sit in the honorifics list.
  Four separate causes, all confirmed:
  - the honorifics list is Western-only, so "Elder Fang Yuan" (94 mentions
    across 35 chapters) strips to nothing, and only a *leading* title is
    stripped, so a two-word rank like "Wolf King Chang Shan Yin" (67 mentions)
    keeps it. An earlier draft of this list cited "Demon King Fang Yuan" here;
    that form occurs **once** in 2,360 chapters, so the reasoning stands but
    the example was a hapax - "Lord" (166) and "Elder" (94) are the forms with
    real volume;
  - **a clan prefix is not a title, and treating the two as one problem is
    itself a cause.** A rank is drawn from a closed vocabulary; "Gu Yue" is a
    family name the book invented, so no honorifics list can ever contain it.
    It precedes 41 distinct personal names and the book also names "Gu Yue
    Clan" and "Gu Yue Village", which is what makes it recognisable without a
    list;
  - the ambiguity guard **inverts**. Refusing a name that sits inside more
    than one longer name is right for two characters sharing a given name,
    but "Fang Yuan" sits inside four longer forms of *itself*, so the richer
    the character, the more certainly nothing is proposed;
  - the one rule that could catch an assumed identity - the book stating the
    link in its own words - is starved by its shortlist, which only ever
    offers it single-token names where one is a prefix of the other. On this
    book the shortlist was empty, so the rule never ran, even though the text
    says "Fang Yuan, the so-called Chang Shan Yin" and "Fang Yuan called
    himself Qi Sea Ancestor".

  **Two things make this harder than it looks, and are why it is not simply
  a matter of loosening the rules.** A name can *transfer*: the same book has
  the protagonist take a historic character's name, so one string means two
  different people depending on the chapter - and the book states the
  non-identity in words a proximity rule reads as the opposite ("I am Fang
  Yuan, not Wu Shuai"). And **aliases carry no chapter scope at all**. Facts
  do, so no merged entity can leak a later fact; what leaks is the alias list
  itself, since showing "Fang Yuan, also known as Qi Sea Ancestor" to a reader
  at chapter 100 gives away a chapter-1853 reveal.

  **The first three causes are fixed; the assumed-identity half is not.**
  The approach that does *not* work is classifying the
  prefix - deciding whether "Lord" is a rank, "Gu Yue" a clan, "But" neither.
  Three classifiers were built against the full text and all three failed; the
  best of them read invented name-parts ("Northern", "Blood", "Star") as ranks
  and read the real ranks "Elder" and "Senior" as neither, because a book's
  invented vocabulary is English-shaped. What works is testing what is *left
  behind*: strip leading tokens from a candidate name only when the remainder
  is itself a better-attested name in the same book. That one rule strips a
  Western honorific, an eastern clan prefix and a book-invented title alike,
  and it needs no wordlist, no new schema field and no re-extraction. It also
  dissolves the inverted ambiguity guard rather than repairing it - each longer
  form is tested against the bare name independently, so four decorated forms
  now produce four links instead of none. **Measured at 240 proposed links
  across the 8-book library, 231 correct (96.3%), hand-checked** - and 237 /
  230 / **97.0%** as shipped, for the reason below. Two guards on
  the remainder are both required, and neither is sufficient alone: without
  "the remainder is not an ordinary English word" it strips surnames and
  category nouns ("Dong Fang" to "Fang"); without "the bare remainder
  outnumbers its own use inside longer names" it strips capitalised pronouns
  ("Qin Bai He" to "He"). **The errors all share one shape** - a qualified
  variety of a category the book names ("Blue Elixir" to "Elixir", "Four
  Flavours Liquor" to "Liquor"), and all of them are in a single book. The
  obvious third guard was built and rejected on cost: requiring the prefix to
  decorate several different identities removes 5 of those errors and loses
  about 53 correct links doing it. So this is propose-only, with the failure
  shape documented rather than guarded against. **It is also not an
  eastern-naming fix**, which was not the expectation - run unchanged over the
  other books it finds "Magister Nevery" and "Underlord Crowe" in *The Magic
  Thief*, "Captain Ahab", "The Aes Sedai" and "The Wargals", all titles a
  closed list cannot hold precisely because the book invented them.

  **Shipped**, and on both paths: as a fourth rule inside
  `doctor --merge-name-variants`, and - since a reader's flow never reaches
  that command - automatically at ingest, before extraction, where it stops
  the split forming at all. See "Titles and other forms of a character's
  name" above for what that looks like. Building it changed the measured
  design twice, both times measured rather than argued:

  - **"Ordinary English word" is now judged per book.** As scored it also
    asked whether the word appeared in 6 of the library's 8 books, which
    cannot ship - a three-book library could never satisfy it, so the rule
    would quietly fall back to one guard. Dropping that term loses 3 links,
    2 of which were errors, which is why the shipped figure is higher than
    the scored one.
  - **Characters only.** The scoring ran over raw text and had no entity
    types in it. Every remaining error is a thing rather than a person, and
    every correct non-character link but one is a "The X" to "X" strip that
    the duplicate-entity check already reports, so the restriction removes
    the whole error class and gives up almost nothing.

  Two caveats worth knowing. The "The Wargals" and "The Aes Sedai" cases
  above are real, but they were **already** found by `--merge-duplicates`,
  which normalises a leading "the" and a trailing "s" - the genuinely new
  reach is a character with *several* decorated forms, which the ambiguity
  guard used to refuse outright. And the dominance requirement now differs
  by path: `doctor` asks for 3x and ingest for 5x, because a proposal you
  decline costs a keystroke and a silent merge costs a re-extraction. The 13
  extra links 3x buys were hand-scored at 10 right, 3 wrong.

  **What this does not touch** is the assumed identities, which are where
  the volume is: it addresses the 0.67% of mentions carrying a title or clan
  prefix, not "Hei Lou Lan" or "Qi Sea Ancestor", which share no words with
  "Fang Yuan". Aliases still carry no chapter scope either, so "Wolf King"
  names its original owner and its later taker alike. See Future ideas.
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
  **It does not own character identity.** Asked whether it could supply the
  identity links third-person books are missing, the answer is no, and the
  dependency runs the other way: a timeline built over entities that are
  still fragmented across nine names attributes one character's arc to nine
  actors, which is a larger version of the bug it exists to fix. Identity
  stays in the alias record, which is shaped as an event
  (`chapter`, `entity`, `name`, `taken_from`, `evidence`) so this construct
  can consume those as its first event type - including the genuinely
  multi-entity case of a name transferring from one character to another.

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
- ~~A single file containing several books ("omnibus"/"bindup") is treated
  as one long book.~~ **Built**, for the epub case. Ingest reads the volume
  boundaries out of the file's own nested table of contents and records
  where each volume starts and ends; citations name the volume and count
  chapters from its start. See [Naming the books inside an
  omnibus](#naming-the-books-inside-an-omnibus-automatically) for the
  detection rules and the measurements behind them.

  Three pieces of the original guess turned out wrong. A *repeated title
  pattern* or a *restarting chapter numbering* was not needed and would not
  have worked: Reverend Insanity's 24 volumes number their chapters
  1–2334 straight through, and Magic Thief's volume titles share a prefix
  rather than repeating. An explicit `--split-at` flag was not built, on
  the same reasoning as the alias work — a reader's flow is download,
  ingest, extract, chat, and a flag they have to know to type is a feature
  that never runs.

  And **splitting the file was not needed at all** — which took building it
  to find out. The first version wrote one `book_id` per volume. It produced
  exactly the citation string the span map produces, and charged for it:
  every chapter outside a volume was deleted, a `--no-split` flag existed to
  escape it, and one source file was archived under one volume and
  back-referenced by its siblings. The deliverable was always a *rendered*
  location; what the database keys a chapter as never mattered.

  Still open: **PDF omnibuses**. `pdf_loader` flattens the outline to level 1
  entries, so a nested PDF arrives as one "chapter" per volume and the
  nesting that would identify the boundaries is already gone. Fixing it means
  teaching `pdf_loader` to keep the outline depth, which is a change to how
  every PDF is chaptered, not just omnibuses.
- ~~Nicknames and alternate names for one character~~ **Partially resolved.**
  Reported from real use: *The Magic Thief*'s protagonist appears as Conn,
  Connwaer, "the boy" and "bird", with facts scattered across all of them.
  `bookrag doctor --merge-name-variants` (see "Managing your library") now
  finds and merges the *name* half of this, which is what finally populates
  the `aliases` field from a book rather than from a hand-run merge. Chosen as
  an offline `doctor`-style pass rather than an extraction field so it needs
  no re-extraction. Run against this project's own 493-entity library it found
  **16 clusters covering 34 entities, all 16 correct** - including "Baron
  Arald"/"Arald" (39 + 10 facts) and a three-way "Battlemaster David"/"Sir
  David"/"David".
  **The epithet half is now closed for first-person narrators.** "The boy"
  shares no string relationship with "Conn", so no rule *here* could reach it;
  it needed a different signal entirely - not what the names look like, but
  who is addressing whom. Ingest now reads forms of address and links them
  before extraction (see "Linking a narrator's names, automatically"), which
  on the reported book captures "boy", "lad", "thief", "shadow", "blackbird"
  and "cousin". That path is first-person only and needs two spellings of a
  name, so it does nothing for most books.
  **The morphology half of the third-person problem is now closed too, and
  also runs at ingest** - a character's titled names are grouped before
  extraction whether or not the book has a first-person narrator (see "Titles
  and other forms of a character's name"). On the reported book that takes
  the protagonist from 1 linked form to 34.
  **What remains open is the assumed identities**, where a character takes a
  wholly different name that shares no words with their own - and that is
  where the volume is. See the matching entry under Known limitations for the
  four confirmed causes and for the two constraints that make it harder than
  loosening the rules: a name can transfer between characters, and an alias
  carries no chapter scope, so an unscoped link is itself a spoiler.
  The planned shape was: fix the name morphology first (it needs no
  re-extraction), then give an alias a `from_chapter`, then widen the
  stated-link rule behind a negation guard. **The morphology half has now
  shipped** - the remainder rule described under Known limitations, which
  covers Western honorifics, eastern clan prefixes and book-invented titles
  with one test and no wordlist. **Whether it should have gone first is still
  an open question**, because the same measurement undercuts the reason it was
  scheduled first: 99.33% of the reported character's 56,456
  mentions are the bare name, every title and clan form together accounts for
  376, and the assumed identities carry roughly 10,270. Morphology is cheap and
  worth doing, but being cheap is not a reason to do it first when the
  chapter-scoped alias is what makes the high-volume half both correct and safe
  to render. **Identity stays in the alias
  record rather than being derived from the planned timeline construct** -
  resolving who a character *is* has to precede attributing events to them,
  or the timeline inherits the fragmentation. The alias record is shaped as
  an event so the timeline can read it instead of re-deriving it.
  Worth recording what the design survey found, since it is counter-intuitive:
  **similar spelling is not evidence of anything.** Proposing a merge whenever
  one name is a prefix of another was 0-for-6 on real data
  ("Machine"/"Machinery", "King"/"Kingdom", "Skandia"/"Skandians"), and
  generic containment across all entity types was right about 8 times in 44 -
  in a book about the difference between a finite game and an infinite one,
  "Finite Game" contains "Game" and means something else entirely.
- **Book-level facts: protagonist, antagonist, cast, main plotline.**
  Requested as a way to ask "who is in this book?" without naming anyone
  first. Today every fact hangs off one entity and there is no book-level
  layer at all (`metadata.json` holds only bibliographic fields). **This is
  the most spoiler-dangerous idea on this list.** It was gated on the
  spoiler-safety tests, which now exist (`tests/test_spoiler_safety.py`, see
  "Running tests") - so the gate is open, but extending those tests to cover
  whatever new render surface this adds is part of building it, not a
  follow-up: equivalence only guards what it is pointed at.
  "Antagonist" and "main plotline" are
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
- ~~Citations back to where a fact came from.~~ **Built** — see
  [Where an answer came from](#where-an-answer-came-from). The fuzzy route
  was the right call: no schema change, no re-extraction, and measured at
  **91% precision over 181 hand-scored statements across six books**.

  **The framing in this entry was wrong in a way worth keeping.** It treated
  the problem as "locate the source text", with the stitched omnibus as a
  blocker because a chapter number would be meaningless. The actual
  requirement is a *rendered location the reader can act on*, and what the
  database keys a chapter as never mattered. That reframing is why the quote
  — not the chapter number, not the page — turned out to be the primary
  locator: it is the only part of a citation that survives a different
  edition. It also means the omnibus split was never a prerequisite — the
  split has since been removed and replaced by a volume *label*, which
  produces the same citation string and deletes nothing.

  Two things this entry did not anticipate, both found by measuring:
  - **Most books already knew their chapter names and ingest was discarding
    them.** Three of eight were classified `text-bound` purely because their
    titles live in the epub's navigation rather than its markup. Reading the
    table of contents took Ranger's Apprentice from 1 titled chapter of 75 to
    75, and The Eye of the World from 0 of 108 to 54.
  - **The two books with no usable titles at all have page numbers**, from a
    PDF outline and from `page_N.html` spine filenames. So no book in the
    corpus falls back to a bare chapter index.

  **The threshold question is closed, and the answer is that it was the
  wrong question.** The first measurement covered one book (49 statements,
  97.5%) and left 0.40-vs-0.50 open. Five more books say the threshold moves
  precision six points across a range that costs forty-one points of
  coverage — and that the one-book figure was optimistic, since the *same
  book* scores 81% on two different chapters. What replaced the question:
  **coverage is a per-chapter property**, set by how much of the model's own
  vocabulary is absent from the chapter (r = −0.81), so no single global
  threshold serves a plainly-written chapter and a summarised one alike.
  Adapting the scoring to that is the real open item.

  Still open: a book that is unpaged *and* whose passage does not match
  stops at the chapter. And the error class worth naming is the near miss —
  one rare word carries the match, so "Gilan inspected the garrison house"
  lands on "He inspected the tip of his finger."
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
- **Autofit: detect available VRAM and size `$OLLAMA_NUM_CTX` (and recommend
  KV-cache settings) automatically**, instead of a user working through the
  "Is a full offload even possible on this machine?" section by hand (see
  above for the current manual levers and the weights+cache formula). Raised
  from a real support case: a user at a partial GPU/CPU split on
  `qwen2.5:7b-instruct` reached for further quantization first, which is
  exactly the lever that section flags as costing output quality for no
  guaranteed win, when the KV cache was the actual fixable part. Not scoped
  yet - needs a planning pass on:
  - Cross-platform free-VRAM detection (`nvidia-smi`/`rocm-smi` parsing, no
    universal API) that degrades to a no-op on CPU-only or unsupported GPUs -
    this project's own dev machine is one.
  - Whether it only ever picks `num_ctx` (already bookrag's knob) or also
    prints/recommends server-side settings (`OLLAMA_KV_CACHE_TYPE`,
    `OLLAMA_NUM_GPU`) it has no authority to set itself - see `base.py`'s
    "bookrag never chooses GPU or CPU - Ollama does" principle, which this
    would need to respect rather than quietly cross.
  - **Whether `bookrag chat` should become continuous (conversation history
    carried across questions) or stay independent (today's behaviour - the
    `input()` loop in `cli.py`'s `_chat` recomputes `select_relevant_facts`/
    `format_context` from scratch per question, with no memory of earlier
    turns).** This has to be decided before autofit's targets are, not after:
    a continuous conversation accumulates prior turns into the prompt and
    needs headroom for that growth, while independent per-question calls only
    ever need to fit one question's retrieved facts - a smaller, flatter
    budget that may make a larger context window unnecessary in the first
    place.
  - **A concrete signal for "facts are being cut off," rather than a
    book-length heuristic.** `select_relevant_facts` (see `query.py`) already
    narrows what's sent per-question, which likely covers most of this in
    practice - but that guards relevance, not confirmation that everything it
    selected actually fit within `num_ctx`. Worth checking whether that
    guarantee already exists before treating this as solved, since autofit
    needs the cutoff signal, not the narrowing, to know when a chosen
    `num_ctx` is too small.

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
