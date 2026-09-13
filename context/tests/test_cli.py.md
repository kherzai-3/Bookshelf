---
source: tests/test_cli.py
last_synced: 2026-09-13T16:40:00Z
source_hash: 9d98b2d844b8c64eb327550a8dff54608d1c6cc8
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

Also covers, added since the above:
- **Model-mismatch refusal at the CLI boundary**
  (`test_extract_refuses_a_model_mismatch_before_announcing_a_resume`): the
  check must run *before* the "Resuming ..." line is printed, so the user is
  never told a resume is happening that is then refused.
- **The ETA denominator** (`test_progress_estimate_ignores_chapters_an_earlier_
  run_already_did`, `..._on_a_fresh_run_counts_every_completed_chapter`): a
  resumed run must divide elapsed time by chapters *this* run did, not by the
  absolute chapter position.
- **Console encoding** (`test_utf8_output_setup_tolerates_a_stream_that_cannot_
  be_reconfigured`): stdout is reconfigured to UTF-8 so a cp1252 Windows
  console doesn't render correct data as mojibake, guarded so an already-
  replaced stream (pytest capture) doesn't break.
- **Content type at the CLI**: `ingest` defaults to fiction, takes an explicit
  `--content-type`, and `chat` reads it back out of `metadata.json` to pick the
  answer prompt.
- **Fragment consolidation at ingest**
  (`test_ingest_consolidates_many_small_fragments`).
- `chat`'s remaining argument handling: an out-of-range `--chapter` and an
  unknown `book_id` both fail cleanly.

## Key Decisions
- The `_library_root` autouse fixture points `BOOKRAG_LIBRARY_ROOT` at a
  `tmp_path` for every test in this module, so nothing here ever touches the
  real `data/library/`.
