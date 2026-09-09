---
source: tests/test_cli.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 1ff7dc73b832f6a1e02ab56d4f10635b279c29ef
---

## Purpose
End-to-end coverage of `bookrag.cli.main`: `ingest` (happy path, series
flags, missing file, unsupported extension, a corrupt file failing cleanly
rather than crashing, the ingestion report being written, and the
incoming-folder auto-delete behavior) plus `extract`/`eval` against
`--provider(s) fake` so no API key is needed, including the per-chapter
progress lines `extract` prints and that `--model` is threaded through to
`get_provider` (verified via a monkeypatched stand-in, not a real call).
Also covers the library-management subcommands at the CLI-plumbing level
(argument parsing, exit codes, printed output) - `library.py`'s own test
module (`tests/test_library.py`) owns the actual list/show/remove/doctor
logic in depth: `list`/`show` output shape and unknown-book-id handling,
`remove`'s `--yes` bypass and its confirmation-prompt abort path
(monkeypatching `builtins.input`), and `doctor`'s report-then-`--fix`-then-
recheck round trip.

Also covers `extract`'s CLI-level resumability behavior (the underlying
logic is `test_extraction_pipeline.py`'s job): an already-fully-extracted
book prints "already fully extracted" and exits 0 without re-running,
`--restart` forces a real re-extraction anyway, and a book with
hand-written `extraction_progress.json` state (simulating a real crash)
prints "Resuming '<book_id>' from chapter N" before the run starts.

Also covers `doctor --merge-duplicates`'s CLI-level confirmation flow
(the actual detection/merge logic is `test_library.py`'s job): a seeded
duplicate cluster is reported in plain `doctor` output, `--yes` merges it
without prompting, and declining the `[y/N]` prompt (monkeypatching
`builtins.input`) leaves both original entities untouched.

Also covers `chat`'s interactive-session behavior change: two different
questions in one session (via a fake multi-answer `input()`) must produce
two *different* recorded `context` values on a `_RecordingProvider`,
confirming retrieval now actually runs per question instead of once
before the loop starts.

## Key Decisions
- The `_library_root` autouse fixture points `BOOKRAG_LIBRARY_ROOT` at a
  `tmp_path` for every test in this module, so nothing here ever touches the
  real `data/library/`.
