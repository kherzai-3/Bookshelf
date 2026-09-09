---
source: tests/test_cli.py
last_synced: 2026-09-09T00:00:00Z
source_hash: 9cb03b4bec122e036f2faff1c4cf804efa366458
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

## Key Decisions
- The `_library_root` autouse fixture points `BOOKRAG_LIBRARY_ROOT` at a
  `tmp_path` for every test in this module, so nothing here ever touches the
  real `data/library/`.
