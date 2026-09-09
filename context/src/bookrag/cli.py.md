---
source: src/bookrag/cli.py
last_synced: 2026-09-09T00:00:00Z
source_hash: e418e34e46b5ec10aaa0d607c1b48ae04d247b80
---

## Purpose
The `bookrag` command-line entry point (registered via `[project.scripts]` in
`pyproject.toml`). Eight subcommands: `ingest` (file → library),
`extract` (library book → chapter-scoped facts), `eval` (compare providers,
read-only), `chat` (spoiler-safe Q&A against a book, up to a given chapter),
and four library-management commands - `list`, `show`, `remove`, `doctor` -
that are thin argparse/print wrappers around `bookrag.library`'s actual logic
(see that file's context doc for the real behavior).

## Public Interface
- `main(argv: list[str] | None = None) -> int` — argparse-based entry point;
  takes an explicit `argv` (rather than always reading `sys.argv`) so tests
  can call it directly without subprocessing.
- CLI: `bookrag ingest <path> [--title] [--author] [--series NAME]
  [--series-position N] [--content-type fiction|nonfiction]` —
  `--series-position` is required whenever `--series` is given (rejected
  with exit code 1 otherwise, before anything is written). `--content-type`
  defaults to `"fiction"`, is persisted to `metadata.json`, and later
  selects which extraction category/entity-type taxonomy and prompt pair
  `extract`/`eval`/`chat` use for this book - explicit, not auto-detected
  (matches this project's posture elsewhere, e.g. `--series-position`).
- CLI: `bookrag extract <book-id> [--provider NAME] [--model NAME]
  [--restart]` — `--provider` is `"anthropic"`, `"ollama"`, or `"fake"`;
  defaults via `providers.registry.get_provider` (`$BOOKRAG_PROVIDER` then
  `registry.DEFAULT_PROVIDER`, currently `"ollama"`). `--model` is a
  one-off override of the provider's own model (e.g. `qwen2.5:7b-instruct`
  for ollama); for a persistent per-machine choice (picking a bigger model
  on a GPU box), `$OLLAMA_MODEL`/`$ANTHROPIC_MODEL` (or a `.env` entry) is
  the intended mechanism instead - `--model` is the one-off escape hatch.
  Resumable (see `extract/pipeline.py`'s context doc): before calling
  `extract_book`, `_extract` peeks `resume_start_index` and prints
  `"Resuming '<book_id>' from chapter N"` up front if there's genuine
  partial progress to continue; if the book is already fully extracted, it
  prints that and returns 0 without calling the provider at all, unless
  `--restart` is passed (which forces a full from-scratch re-extraction,
  the old unconditional-overwrite behavior). A `KeyboardInterrupt` during
  the run is caught specifically (progress is already saved by
  `extract_book` itself by the time it propagates here) and printed as
  "Interrupted - progress has been saved..." rather than a raw traceback.
- CLI: `bookrag eval <book-id> --chapters 0,1,2 [--providers ollama,fake]
  [--model NAME]` — comma-separated chapter indices and provider names;
  malformed `--chapters` is rejected with exit code 1 before running
  anything. `--model` applies the same override to every provider listed
  (doesn't support comparing two different models of the *same* provider
  in one run - `providers` is keyed by provider name, so e.g. `ollama,ollama`
  would collapse to one entry).
- CLI: `bookrag chat <book-id> --chapter N [--provider NAME] [--model NAME]
  [--question TEXT]` — `--chapter` (0-indexed, required) is the reader's
  current position; facts past it are never shown to the provider (goes
  through `query.facts_as_of`/`query.format_context`). With `--question`,
  answers once and exits (exit 1 if the book or chapter is invalid, same
  posture as `extract`/`eval`); without it, starts an interactive
  `> `-prompt loop, one answer per line, until EOF/Ctrl+C.
- CLI: `bookrag list` — table of every book in the library: id, title,
  author, chapter count, content type, extraction status (fact count, or
  `N (partial: M/total ch)` when the run hasn't reached the end yet, or `-`
  if never extracted), series. An orphaned index entry (see `library.py`)
  prints as a distinct `ORPHANED` row rather than crashing.
- CLI: `bookrag show <book-id>` — the same per-book detail `list` summarizes,
  spelled out (entity count included, which the table omits for space).
  Exit 1 for an unknown `book_id` or an orphaned one (points at
  `bookrag doctor --fix` instead of failing silently).
- CLI: `bookrag remove <book-id> [--yes]` — deletes the book's library
  directory, its `index.json` entry, and prunes it from every entity's
  `book_ids` in `entities.json` (see `library.remove_book`). Prompts for
  confirmation (`input()`, same interactive pattern as `chat`'s loop) unless
  `--yes` is given; an unconfirmable prompt (EOF, e.g. non-interactive
  stdin) aborts rather than silently proceeding. Works even on a
  directory-only-orphaned or index-only-orphaned book.
- CLI: `bookrag doctor [--fix]` — reports (or, with `--fix`, also repairs)
  three kinds of library drift: orphaned `index.json` entries, stale
  `entity_id -> book_id` references, and entities with zero facts
  referencing them in any book that still exists. Read-only by default -
  see `library.run_doctor` for exactly what `--fix` changes.

## Key Decisions
- Loader is selected by file extension (`.epub` → `epub_loader`, `.pdf` →
  `pdf_loader`) via the `LOADERS` dict — any other extension is rejected.
- Title/author precedence: explicit `--title`/`--author` flag > metadata
  extracted from the file itself > `titles.guess_title_author` on the
  filename stem > (title only) the raw filename stem. When metadata is
  missing and a value gets guessed from the filename, a note is printed
  (`"(no title in file metadata - guessed '...' from filename)"`) so a bad
  guess is visible rather than silently wrong — this was added after real
  Gutenberg/PDF test files showed metadata is often absent.
- `_ingest` wraps loader parsing and `save_book` in separate `try/except
  Exception` blocks, printing a clean one-line error and returning 1
  instead of letting a corrupt/malformed file crash the CLI with a raw
  traceback (real-world epubs from unofficial sources are not guaranteed
  well-formed). `save_book` failing leaves nothing to clean up here since
  it rolls back its own partial `book_dir` (see `storage.py`).
- On successful ingest, `_remove_if_from_incoming` deletes the source file
  **only if** it resolves to a path under `storage.incoming_root()` -
  deliberately narrow, since auto-deleting an arbitrary user file outside
  the designated staging folder would be a surprising, unrequested
  destructive action. A deletion failure (permissions, etc.) is reported,
  not raised - it shouldn't undo an otherwise-successful ingest.
- `_extract`/`_eval` wrap `get_provider(...)` and the actual
  extract/eval call in separate `try/except Exception` blocks, same
  posture as `_ingest` - a bad provider name, missing API key, or the
  provider being unreachable prints a clean one-line message and returns 1
  instead of a raw traceback.
- `_extract` prints `result.parse_failure_count`,
  `result.ungrounded_entity_count`, and `result.skipped_chapter_count` when
  non-zero, so a chapter `extract_book` had to skip (malformed output, a
  likely-hallucinated new entity, or too short to plausibly be narrative -
  see `pipeline.py`), is visible in the CLI output rather than silently
  absorbed.
- `_chat` validates `--chapter` against the book's actual chapter count
  (via `load_chapters`) before calling `facts_as_of` - `facts_as_of` itself
  doesn't range-check (an out-of-range chapter would just silently include
  every fact), so this is the one place that turns a typo'd chapter number
  into a clear error instead of a quietly-too-generous answer. It also
  loads the book's `content_type` (`load_metadata(...).get("content_type",
  "fiction")`) alongside the chapter count, passed to every
  `answer_question` call so a nonfiction book gets the nonfiction answer
  prompt.
- `_ingest` calls `ingest.consolidate.should_consolidate`/
  `consolidate_fragments` right after `loader.load_chapters`, before
  `sanity_summary`/`classify_ingestion`/`save_book` all run - so every
  downstream consumer sees the (possibly consolidated) chapter list, never
  the raw one. `raw_chapter_count` is threaded through to
  `write_ingestion_report` (as `None` when nothing changed) purely so the
  consolidation note is visible on later review of the report file, not
  just in the terminal at ingest time.

## Public Interface (continued)
- `classify_ingestion(chapters) -> "chapter-bound" | "text-bound"` —
  `"chapter-bound"` if more than half the chapters carry a real title
  (heading/TOC signal found), else `"text-bound"` (fell back to raw
  page/spine fragmentation - see epub_loader/pdf_loader "no exploitable
  structure" cases). Empty chapter list is `"text-bound"`.
- `_print_progress(start_time: float) -> OnChapterDone` — returns a closure
  suitable for `extract_book`'s `on_chapter_done`; prints
  `"[N/total] chapter done - elapsed Xs, ~Ys remaining"` per chapter, ETA
  estimated as `(elapsed / done) * remaining_count`. Added once a real
  75-chapter extraction against a local model took long enough (minutes) to
  need visible progress. Prints with `flush=True` - without it, a
  backgrounded run's progress is invisible until process exit (Python fully
  buffers stdout when it isn't a real terminal), which is exactly the
  problem this feature exists to solve.
- `_format_duration(seconds: float) -> str` — `"45s"` / `"3m12s"` /
  `"1h2m3s"`, whichever units are non-zero.
- `write_ingestion_report(book_id, chapters, root=None, raw_chapter_count=None) -> Path`
  — writes `data/library/<book_id>/ingestion_report.txt`: the
  classification plus everything `sanity_summary` prints, persisted rather
  than only shown at ingest time. When `raw_chapter_count` is given (and
  differs from `len(chapters)`), appends a note that fragments were
  consolidated (see `ingest/consolidate.py`) with the before/after counts.
  When `"text-bound"`, appends a note that chapter-scoped cataloging/
  spoiler-safe querying still work correctly against the fragment
  boundaries - they just won't align with the book's real chapters/TOC.
- `sanity_summary(chapters: list[Chapter], edge_count: int = 3) -> list[str]`
  — printed after every ingest: min/median/max chapter word count, plus the
  first and last `edge_count` chapter titles. Chapter extraction is
  heuristic (see `epub_loader`/`pdf_loader`) and can misfire quietly on an
  unusual book; this is deliberately a human-reviewable summary rather than
  an attempt to auto-detect every failure mode (validated against real
  files: it immediately surfaces Gutenberg front/back-matter noise and a
  PDF whose TOC entries are meaningless internal bookmark IDs).

## Dependencies
- Internal: `bookrag.ingest.epub_loader`, `bookrag.ingest.pdf_loader`,
  `bookrag.ingest.chapter.Chapter`, `bookrag.ingest.consolidate`
  (`should_consolidate`, `consolidate_fragments`), `bookrag.storage`
  (`save_book`, `load_chapters`, `load_metadata`, `library_root`,
  `incoming_root`), `bookrag.titles.guess_title_author`,
  `bookrag.extract.pipeline` (`extract_book`, `resume_start_index`), `bookrag.eval` (`run_eval`,
  `summarize`), `bookrag.providers.registry.get_provider`, `bookrag.query`
  (`facts_as_of`, `format_context`), `bookrag.library` (`list_books`,
  `show_book`, `remove_book`, `run_doctor`)
- External: `statistics` (stdlib)

## Open Questions / TODOs
- The non-fiction taxonomy (`--content-type nonfiction`, see
  `providers/prompts.py`/`providers/parsing.py`) has only been validated
  via a `bookrag eval` checkpoint (3 chapters of a real consolidated Atomic
  Habits), not a full real extraction run - see `pipeline.py`'s context
  doc; flagged here as needing a full real extraction run before it can be
  considered fully validated.
- `chat`'s interactive loop re-answers every question against the same
  fixed `context` string built once at startup - there's no multi-turn
  conversation memory (the provider never sees earlier Q&A in the session),
  and no way to bump `--chapter` mid-session as the reader progresses
  without restarting.
- **No cleanup/trim command exists.** `sanity_summary` is diagnostic only —
  if it reveals bad chapters, there's currently no way to fix them up short
  of re-ingesting (which doesn't touch chapter boundaries). A `bookrag trim
  <book-id>` or similar is a known, deliberately deferred gap (see README's
  Known Limitations).
