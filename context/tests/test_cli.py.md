---
source: tests/test_cli.py
last_synced: 2026-09-15T14:49:45Z
source_hash: e16b95a6018dd86598394cf067960789661f6a25
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

Also covers `doctor --merge-name-variants`'s CLI plumbing (the detection logic
is `test_library.py`'s job): `test_doctor_reports_a_name_variant_cluster_with_
its_evidence` asserts the report says *why* and not just which names - the user
is approving a permanent rewrite of fact ownership, so the evidence is the
basis for saying yes; `..._with_yes_records_the_other_name_as_an_alias` pins the
actual payoff (the survivor gains "Arald" as an alias, the field
`select_relevant_facts` has always searched and nothing populated from a book);
`..._declined_leaves_both_entities_alone` and
`test_doctor_fix_never_merges_a_name_variant` pin the two refusal paths.

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
  never told a resume is happening that is then refused. It now also asserts
  `"Extracting" not in out` — the start-of-run banner has to be withheld by
  the same refusal, for the same reason.
- **Output sectioning** (`test_print_section_omits_an_empty_section_entirely`,
  `..._renders_a_heading_and_indents_its_content`,
  `test_ingest_groups_its_output_under_headings`,
  `test_extract_separates_its_result_from_the_progress_lines`): the ingest
  test asserts the *order* of the four headings and that the consolidation
  note now falls below "Parsing:", which is the actual regression — the parse
  notes used to print above the headline they qualified. The empty-section
  test pins the invariant the rest depends on: a header with nothing under it
  is worse than no header, and "Skipped and rejected" is empty on a healthy
  run.
- **The start-of-run banner**
  (`test_extract_announces_the_run_before_the_first_chapter_completes`):
  asserts on the *ordering* (`output.index("Extracting") <
  output.index("chapter done")`), not merely that the banner appears — its
  whole purpose is being emitted before the first chapter's silence, so a test
  that only checked presence would pass even if it printed at the end.
  `test_extract_start_notes_name_the_model_and_omit_it_when_unknown` covers
  the identity clause directly: present for a provider that offers one, and
  absent (never `"via None"`) for the many minimal test doubles that don't.
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
- **Post-ingest guidance and `--log`** — the two halves of "how do I follow the
  extraction?": `test_ingest_tells_the_user_how_to_extract` and
  `..._how_to_follow_a_long_run` assert ingest names the next command and the
  log/follow recipe, with the second pinning that the path ingest *prints* is
  the path `--log` actually *writes* (`..._uses_the_documented_default`) - if
  those diverge the printed follow command is simply wrong.
  `..._still_prints_to_the_console` pins that `--log` tees rather than
  redirects, `..._appends_so_a_resumed_run_keeps_the_earlier_output` pins
  append-not-truncate, and an unusable path exits 1 instead of raising.
  `test_tee_flushes_every_write_so_a_follower_sees_progress_live` reads the log
  while its handle is still open - what a `tail -f` in another terminal does -
  and is the one test that would catch the log going silent for minutes at a
  time. Sabotage-verified by removing `_Tee`'s flush.

## Key Decisions
- The `_library_root` autouse fixture points `BOOKRAG_LIBRARY_ROOT` at a
  `tmp_path` for every test in this module, so nothing here ever touches the
  real `data/library/`.
