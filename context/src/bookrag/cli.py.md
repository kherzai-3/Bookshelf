---
source: src/bookrag/cli.py
last_synced: 2026-09-22T21:20:00Z
source_hash: 131fa68a61aa52a99ff8aa40bba1428a92820ae1
---

## Purpose
The `bookrag` command-line entry point (registered via `[project.scripts]` in
`pyproject.toml`). Nine subcommands: `ingest` (file → library),
`extract` (library book → chapter-scoped facts), `eval` (compare providers,
read-only), `chat` (spoiler-safe Q&A against a book, up to a given chapter),
and five library-management commands - `list`, `show`, `remove`, `aliases`,
`doctor` - that are thin argparse/print wrappers around `bookrag.library`'s
actual logic (see that file's context doc for the real behavior).

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
- `default_log_path(book_id) -> Path` — `<tempdir>/extract_<book_id>.log`, the
  path `--log` uses by default. Public because `ingest` prints it before
  `extract` ever runs; the command that starts a six-hour run and the command
  that follows it are typed at different times, often in different terminals.
- `placement_notes(provider) -> list[str]` — human-readable lines describing
  where the model is running (fully on GPU / partially / CPU-only), or `[]`
  when it can't be determined. Reported once per run by
  `_progress_and_placement`, after the first completed chapter.
- `_print_section(header, lines) -> None` — a titled, indented block preceded
  by a blank line. Prints **nothing at all** for an empty `lines`, header
  included; see Key Decisions.
- `no_narrator_names_lines(book_id, found: NarratorAliases) -> list[str]` — why
  `bookrag aliases` found nothing, stated as what was measured rather than as a
  claim about the book. It replaced `'<book>' reads as first-person, but no name
  is used for the narrator often enough to report`, which leaned on
  `is_first_person` (true if **one** chapter clears the density gate) and was
  therefore false for three of the eight books in the corpus — Reverend Insanity
  1/2334, Atomic Habits 2/36, Moby Dick 11/142 — and then blamed the absent
  names on the data. The chapter counts now lead and are always printed; the
  sentence after them picks one of three branches (no first-person chapters at
  all / too small a share / genuinely first person throughout). Deliberately
  never says "third person" for the middle branch: Moby Dick is narrated by
  Ishmael throughout and only fails the density gate because most chapters are
  expository, so that wording would be wrong in the other direction.
- `narrator_alias_lines(found: NarratorAliases) -> list[str]` — renders
  `ingest.vocatives.detect_narrator_aliases`'s result under ingest's "Names for
  the narrator" section. Returns `[]` for a third-person book, which is most of
  them, so `_print_section` drops the section entirely and the call site needs
  no guard. Counts are shown deliberately: they are how a reader separates a
  real alias from a stray match, and on a real book the gap is stark (34
  against 2). Each candidate is marked `name` or `epithet`, since that decides
  what can happen to it — only a name is linkable, and only a name ever reaches
  question matching. The section reports and claims nothing about what was
  *applied*; the "Linked" section immediately after is the sole authority on
  that, because a three-party scene can put a bystander's title in this list
  and "detected" must not read as "acted on".

  **It read `found.aliases` as `(name, count)` tuples long after they became
  `AliasCandidate` objects**, so every first-person book crashed here at ingest
  with a `TypeError`. The suite stayed green because the only test covering it
  built its fixture from tuples too — both halves agreed with each other and
  neither with production. Found by `test_cli.py`'s first real ingest of a
  first-person epub; the lesson is that a hand-built fixture for a dataclass
  that recently changed shape is worth nothing.
- `next_step_lines(book_id, chapter_count) -> list[str]` — the post-ingest
  guidance (the `extract` command, the `--log`/follow recipe, that Ctrl+C is
  safe, the `--provider fake` path). Returns lines so `_print_section` owns
  the heading; the relative indent within them is real structure, a command
  sitting under the sentence that introduces it.
- `extract_start_notes(book_id, chapter_count, start_index, provider) ->
  list[str]` — what the run is about to do, printed *before* the first chapter
  rather than after it. Names the book, how many chapters this call will
  process (the remaining count on a resumed run, not the book total), and the
  provider identity when the provider offers one — `via None` would be worse
  than saying nothing, so an unidentified provider simply omits the clause.
  See Key Decisions for the user-reported bug this exists for.
- `follow_commands(log_path) -> list[str]` — the shell command(s) for watching
  a log grow on this platform. Windows returns both `tail -f` (Git Bash, where
  this project is actually developed) and `Get-Content -Wait` (PowerShell);
  printing only one would be wrong for about half the readers.
- CLI: `bookrag extract <book-id> [--provider NAME] [--model NAME]
  [--restart] [--log [PATH]]` — `--provider` is `"anthropic"`, `"ollama"`, or `"fake"`;
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
  `--log` **tees** the run's output to a file as well as the console (via
  `_Tee` + `contextlib.redirect_stdout`), rather than redirecting it — a
  foreground run must still print progress to the terminal. With no PATH it
  uses `default_log_path`. The file is **appended**, not truncated, and each
  run writes a timestamped header: an interrupted run is resumed with the same
  command, so the earlier attempt's output is exactly the context you want when
  working out why it stopped. An unusable path is reported and exits 1 rather
  than raising.
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
  through `query.facts_as_of`, then `query.select_relevant_facts`/
  `query.format_context` - see Key Decisions for why those run per
  question, not once). With `--question`, answers once and exits (exit 1
  if the book or chapter is invalid, same posture as `extract`/`eval`);
  without it, starts an interactive `> `-prompt loop, one answer per line,
  until EOF/Ctrl+C.
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
- CLI: `bookrag aliases <book-id> [--link NAME,NAME,...]` — without `--link`,
  reports what `ingest.vocatives` found (the same detection ingest prints,
  re-run from stored chapters, so no new storage format was needed), plus the
  candidates it *rejected* as other characters and why. With `--link`, calls
  `library.link_names`. **The point of the command is the ordering it teaches:**
  linking before `extract` stops the split forming, linking after merges what
  already exists. Says plainly that a third-person book has nothing to report,
  rather than printing an empty list that reads like a failure. The example
  command it prints joins names with a bare comma and no space - a cast
  routinely includes names a shell would split on, and that line is meant to be
  copied verbatim. It also warns, above the example, to prefer real names over
  generic terms of address, because aliases match by substring.
- CLI: `bookrag doctor [--fix] [--merge-duplicates] [--merge-name-variants]
  [--split-cross-book] [--yes]` — reports (or, with `--fix`, also repairs)
  three kinds of library drift: orphaned `index.json` entries, stale
  `entity_id -> book_id` references, and entities with zero facts referencing
  them in any book that still exists.
  Also always reports possible-duplicate entity clusters (same name across
  types/spellings - see `library.detect_duplicate_entities`), but `--fix`
  never touches them - that needs the separate `--merge-duplicates` flag,
  which confirms per cluster (`[y/N]`, same pattern as `bookrag remove`)
  unless `--yes` is given, defaulting to the most-facts entity in each
  cluster as the one kept. Read-only by default - see `library.run_doctor`/
  `library.merge_entities` for exactly what each flag changes.
- `--merge-name-variants` is the same shape for a different detector
  (`library.detect_name_variants`): one person under several names, e.g.
  "Baron Arald" and "Arald". The report prints the cluster's *reasons*
  underneath it, and the confirmation prompt repeats them, because the user is
  approving a permanent rewrite of fact ownership and the evidence is the
  whole basis for saying yes.
- `_confirm_and_merge(groups, assume_yes) -> int | None` — the per-cluster
  decision shared by `--merge-duplicates` and `--merge-name-variants`. Both end
  in the same question and the same `merge_entities` call; only the evidence
  line differs. Returns an exit code **only** when the run aborts (an
  unconfirmable prompt), so a caller can tell "finished" from "gave up" -
  hence `int | None` rather than a plain int. `DuplicateEntity` and
  `NameVariant` deliberately carry the same four display fields so one helper
  formats both.

## Key Decisions
- **`extract` announces the run before starting it, not after the first
  chapter.** A real user reported a fresh `bookrag extract` as a frozen run,
  and from the outside it was indistinguishable from one: the only pre-loop
  message was the "Resuming…" line, which a first run skips by definition, so
  nothing at all printed until chapter 1 completed. Two slow things happen
  first, both silent — Ollama loads several GB of weights on a cold start,
  then the chapter itself runs (60s at best measured, minutes on CPU) — for a
  combined one to five minutes of nothing. `extract_start_notes` prints what
  the run is about to do plus an explicit "silence here is normal, not a
  hang". The run itself is unchanged; only the timing of what it says.
  - Printed with `flush=True`, matching the per-chapter progress line. A
    backgrounded run's stdout is block-buffered, so an unflushed banner would
    sit in the buffer for minutes and reproduce the exact bug it exists to
    fix. (`--log`'s `_Tee` flushes on every write regardless; plain `>`
    redirection does not.)
  - Emitted **after** `resume_blocker`'s refusal, for the same reason the
    "Resuming…" line is: a refused run never starts, so announcing what it is
    about to extract is exactly as wrong. Pinned by
    `test_extract_refuses_a_model_mismatch_before_announcing_a_resume`, which
    now asserts the banner is withheld too.
- **Every path in a printed hint is quoted, deliberately.** `bookrag list`'s
  empty-library hint says ``bookrag ingest "<path>"``, with the quotes. Book
  filenames routinely contain apostrophes, and an unquoted apostrophe in
  PowerShell opens a string literal that never closes - the command then never
  runs at all, leaving a `>>` continuation prompt that is indistinguishable
  from a hung ingest. A real user lost an afternoon to exactly this, and
  `ollama ps` showing nothing was the confirming signal rather than a second
  mystery. The hint is read by someone with an empty library, i.e. precisely
  the person about to type their first book filename. Same change in
  `install.py`'s post-install instructions and throughout `README.md`.
- **Both commands group their output into titled sections** (`_print_section`).
  Ingest ran four unrelated concerns together - the result line, the sanity
  summary, housekeeping, and next steps - with two-space indentation doing all
  the work of separation, and `extract`'s closing result ran straight on from
  the last of up to 75 progress lines. Ingest is now **Parsing / Sanity check
  / Files / Next steps** under the headline; extract is the result, then
  **Skipped and rejected**. Nothing here adds information; it only groups what
  was already said.
  - **An empty section prints nothing at all**, header included. That is what
    lets a caller pass a usually-empty list without guarding the call site -
    "Skipped and rejected" is empty on a healthy run, which is the common
    case, and "Parsing" is empty for a well-formed book.
  - The parse notes (consolidation, guessed title/author) are **collected and
    printed after the headline** rather than as they occur. Printing them
    inline put indented detail *above* the un-indented result line it was
    qualifying, which read backwards. Pinned by
    `test_ingest_groups_its_output_under_headings`, which asserts the ordering
    rather than merely that the sections exist.
  - Renamed with this change: `_print_next_steps` → `next_step_lines` and
    `_remove_if_from_incoming` → `_incoming_cleanup_notes`. Both now **return
    lines instead of printing them**, so `_print_section` owns the heading and
    the outer indent, and the cleanup note lands in the same "Files" section
    as the ingestion report - both are statements about what the command did
    to files on disk.
- **`ingest` ends by printing the next command** (`next_step_lines`).
  Reported gap: nothing anywhere told a user that ingesting does not extract,
  what to run next, or that the next step takes hours. The guidance names the
  `extract` command, the `--log`/follow recipe, the fact that Ctrl+C is safe,
  and the `--provider fake` path for trying the pipeline instantly.
- **`ingest` does not start the extraction itself**, considered and rejected:
  a multi-hour, machine-saturating job should not begin as a side effect of
  reading a file into the library. Ingest works with no Ollama running at all,
  and ingesting several books in a row would otherwise launch several runs at
  once. The user chose guidance over auto-start deliberately.
- **`extract` reports GPU/CPU placement once, after the first chapter**
  (`_progress_and_placement` → `placement_notes`). A run that is silently
  CPU-bound looks identical to a fast one until hours have gone by; this is the
  cheapest possible warning. Deferred to after chapter 1 because Ollama can
  only answer once it has loaded a model, and forcing a multi-GB load before
  any work starts is the worse trade — chapter 1 of 75 is still early enough to
  act on. A full offload prints one reassuring line and warns about nothing;
  an undeterminable placement prints nothing at all, since silence beats a
  misleading guess. bookrag does not *choose* GPU or CPU and cannot — see
  `providers/base.py`'s context doc.
- **`_Tee` flushes on every write.** Python block-buffers a file, so an
  unflushed log shows a `tail -f` follower nothing for minutes at a time
  during a job whose entire purpose is watching it progress. Covered by
  `test_tee_flushes_every_write_so_a_follower_sees_progress_live`, which reads
  the log while the handle is still open - exactly what a follower does.
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
- On successful ingest, `_incoming_cleanup_notes` deletes the source file
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
  `result.ungrounded_entity_count`, `result.skipped_chapter_count`, and
  `result.duplicate_fact_count` when non-zero, so anything `extract_book`
  had to skip or drop (malformed output, a likely-hallucinated new entity,
  too short to plausibly be narrative, or an exact-duplicate fact within a
  chapter - see `pipeline.py`) is visible in the CLI output rather than
  silently absorbed.
- `_chat` validates `--chapter` against the book's actual chapter count
  (via `load_chapters`) before calling `facts_as_of` - `facts_as_of` itself
  doesn't range-check (an out-of-range chapter would just silently include
  every fact), so this is the one place that turns a typo'd chapter number
  into a clear error instead of a quietly-too-generous answer. It also
  loads the book's `content_type` (`load_metadata(...).get("content_type",
  "fiction")`) alongside the chapter count, passed to every
  `answer_question` call so a nonfiction book gets the nonfiction answer
  prompt.
- **`select_relevant_facts`/`format_context` are called per question, not
  once before the interactive loop starts.** Changed from the original
  design (context built once, reused verbatim for every question in a
  session) specifically because retrieval is now question-dependent - a
  fixed context computed before the first question is even typed can't
  reflect what that question is about. `facts_as_of`'s result is still
  fetched once per `_chat` call (chapter-scoped, not question-scoped, so
  it doesn't need recomputing per question). `_chat` also threads the book's
  `content_type` into `format_context` (not just into `answer_question`),
  since it selects which categories render as occurrences vs standing
  description - see `query.py`'s context doc.
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
- `_print_progress(start_time: float, start_index: int = 0) -> OnChapterDone`
  — returns a closure suitable for `extract_book`'s `on_chapter_done`; prints
  `"[N/total] chapter done - elapsed Xs, ~Ys remaining"` per chapter, ETA
  estimated as `(elapsed / (done - start_index)) * remaining_count`. Added
  once a real 75-chapter extraction against a local model took long enough
  (minutes) to need visible progress. Prints with `flush=True` - without it, a
  backgrounded run's progress is invisible until process exit (Python fully
  buffers stdout when it isn't a real terminal), which is exactly the
  problem this feature exists to solve.
  `start_index` exists because `done` is the *absolute* chapter position
  (`extract_book` enumerates from `start_index + 1`) while `start_time` only
  covers chapters this run processed - dividing by `done` credits elapsed time
  to chapters an earlier run already paid for. Real case: a resume from
  chapter 11 of 75 divided by 56 instead of 45 and reported ~60 minutes left
  when ~75 was honest. Caller passes the same `start_index` it uses for the
  "Resuming from chapter N" message.
- `_use_utf8_output() -> None` — reconfigures `sys.stdout`/`sys.stderr` to
  UTF-8 at the top of `main()`. Real book text is full of curly quotes
  (U+2019) and dashes, but a Windows console defaults to a legacy code page
  (cp1252 observed on this machine), so correctly-stored facts printed by
  `chat` came out as mojibake (`"Ranger<?>s cloak"`) - clean data looking
  like a corrupted extraction, which is worse than a visible error because it
  erodes trust in output that is actually fine. Display-only; nothing about
  what's stored changes. Each `reconfigure` call is individually guarded
  (`AttributeError`/`ValueError`) because a replaced stream - pytest's
  capture, a `StringIO` - may not implement it.
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
  — printed after every ingest under the "Sanity check" heading:
  min/median/max chapter word count, plus the first and last `edge_count`
  chapter titles. **Returns content, not formatting** — the lines are
  unindented, and each consumer applies its own (`_print_section` on the
  console, `write_ingestion_report` in the file). Chapter extraction is
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
  (`facts_as_of`, `select_relevant_facts`, `format_context`), `bookrag.library` (`list_books`,
  `show_book`, `remove_book`, `run_doctor`, `detect_duplicate_entities`,
  `merge_entities`)
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

## `extract`: refusing a resume before announcing one

`_extract` calls `pipeline.resume_blocker` between computing `start_index`
and printing `"Resuming '<book>' from chapter N"`. Ordering is the whole
point: `extract_book` would raise the same mismatch on its own, but only
after the CLI had already told the user a multi-hour run was under way. On a
block it prints `Refusing to resume '<book>': <message>` and returns 1
without touching the provider or the progress file.

## `doctor --split-cross-book`

Reports entities shared by unrelated books and, with the flag, splits them.
Mirrors `--merge-duplicates`: detection is always shown, the mutation is
opt-in and never folded into `--fix`, because it rewrites fact records across
book directories. Unlike `--merge-duplicates` it needs no confirmation
prompt - there is no judgement call about which entity to keep, since the
split is determined entirely by which book each fact already lives in.

## Automatic linking at ingest

Two linkers run at the end of `_ingest` and print into one "Linked" section.
`auto_link_narrator` handles a *first-person narrator's* several names;
`auto_link_title_variants` handles *any character* whose name also appears
decorated. Both exist for the same reason and both are governed by
`ingest --no-auto-link`.

### `auto_link_title_variants(book_id, chapters, enabled) -> list[str]`

The third-person counterpart, build-order 02c. `doctor
--merge-name-variants` has been able to find these since rank 02 and a
reader's flow never reaches it; a link nobody performs is a link that never
happens.

- **It has to run before extraction to be worth anything.** `resolve_entity`
  matches an incoming name against a known entity's aliases, so an entity
  already carrying "Lord Fang Yuan" absorbs the chapter-110 mention instead of
  minting a second character. Run afterwards the same evidence only supports a
  merge, which is what `doctor` offers.
- **A different guard from `doctor`'s, because the evidence differs.** After
  extraction there are entity types; here there are none, so
  `names.reads_as_a_person` reads personhood out of the prose. This is not
  fussiness: `seed_alias_group` writes `type="character"`, so linking a place
  would be inert as well as wrong — extraction would mint its own setting
  entity and leave the seeded one an orphan.
- **A stricter ratio than `doctor`'s**, for the same reason: a wrong merge
  here is silent and undoing it means `--unlink` plus a re-extraction. See
  `names.py`'s context doc.
- **Announces the wait before taking it.** The scan is ~2 minutes on the
  2,360-chapter book, and a silent two minutes mid-ingest is indistinguishable
  from a hang — the complaint that produced `extract_start_notes`. Printed
  with `flush=True` for the same reason that banner is.
- **Prints counts, not forms, once a group gets large.** The protagonist of a
  long book collects 33 decorated forms, most of them sentence-initial
  ordinary words (`But Fang Yuan`, `And Fang Yuan`). Those are linked
  deliberately and correctly — the rule never has to decide what the prefix
  is — but listing them reads as a bug. They are harmless downstream:
  `resolve_entity` matches an alias exactly, and
  `query._name_matches_question` needs the whole alias to appear in the
  question. So groups of 2 or fewer are listed, larger ones are counted, and
  `bookrag aliases <book>` has the full list.

### `auto_link_narrator(book_id, found, enabled) -> list[str]`
- called at the
  end of `_ingest`, printed under a "Linked" section. **This is what makes the
  detection worth running.** A reader's flow is download → `data/incoming/` →
  ingest → extract, so a feature waiting to be invoked is invisible - exactly
  the fault of `doctor --merge-name-variants`. An interactive prompt was built
  first and removed: it needs a person present who can judge a book's cast, per
  book, which neither scales nor works for a tester.
- Says what it linked and how to undo it, because this is an automatic mutation
  from a heuristic. `ingest --no-auto-link` produces the unlinked baseline.
- `unlinked_narrator_warning(book_id, chapters)` — printed before a run when
  candidates exist and nothing is linked. The last cheap moment before hours of
  work bake a split character in. A warning, never a refusal. `_run_extract`
  keeps the `chapters` list rather than only its length so this can read it.

  Silent on the normal path now that ingest auto-links, so **the only two ways
  to reach it are reversibility paths**: `ingest --no-auto-link`, or
  `aliases --unlink`. That is how it shipped crashing — it unpacked
  `found.aliases` as `(name, count)` tuples after they became
  `AliasCandidate` objects, so `extract` died with a `TypeError` for exactly
  the user who had just undone a link, and `--unlink`'s own message tells them
  to re-run `extract --restart`. The single documented recovery instruction was
  the one that did not work. Ingest-only tests cannot catch it: nothing is
  declared *yet* at ingest time either way, so it takes an extract that runs
  *after* the opt-out.
- `bookrag aliases <book> [--link A,B] [--auto] [--unlink]` — inspect, link by
  hand, apply the same automatic rule to an already-ingested book, or undo. The
  report marks each candidate `(name)` or `(epithet)`, which is the distinction
  that decides where it may be used.
