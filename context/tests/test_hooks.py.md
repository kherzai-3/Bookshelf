---
source: tests/test_hooks.py
last_synced: 2026-09-17T16:02:00Z
source_hash: 9e39987092353d5392407896638a63c5136f57a2
---

## Purpose
Covers the context-doc enforcement hooks themselves (`track_dirty.sh`,
`check_dirty.sh`, `check_drift.sh`). They are bash rather than part of the
package and had no coverage at all — which is how `tests/` stayed
detected-but-not-blocked long enough for eleven test context docs to drift
unnoticed. The rule they implement is a project guarantee, so it is tested like
any other.

## Public Interface
- `run_hook(name, payload, root)` — runs a real hook script against a
  throwaway project root, via `CLAUDE_PROJECT_DIR`.
- `track(root, edited)` — runs `track_dirty.sh` for an edit to `edited` and
  returns the resulting `dirty.txt` lines.
- `sha1_of(text)` — the hash the convention records: CR-stripped, matching
  `tr -d '\r' < <file> | sha1sum`.
- `seed(root, relative, body, *, doc_hash="match")` — writes a source file and
  its context doc. `"match"` records the real hash (in sync), any other string
  is recorded verbatim (drifted), `None` writes no doc at all.
- `drift(root)` — runs `check_drift.sh` and returns its `additionalContext`, or
  `""` when the hook is silent.

## Key Decisions
- **Every test uses `tmp_path` as the project root**, so running the suite can
  never write to this repo's own `.claude/context_state/dirty.txt`. A test that
  polluted the real dirty file would block the turn that ran it.
- **What must be tracked** by `track_dirty.sh`: `.py` under `tests/` (the
  guarantee this exists for), anything under `src/`, and `pyproject.toml`.
  **What must not**: a non-`.py` fixture file under `tests/` (no context doc
  exists for it, so blocking would be a dead end), a `__pycache__` artifact, a
  file outside both directories, and a file outside the project entirely.
- `test_stop_hook_still_emits_valid_json_for_a_crlf_dirty_file` covers a real
  bug this module found: a CR reaching the reason string made the hook's JSON
  unparseable, so the block decision was dropped and the hook failed **open**.
  For a hook whose entire job is blocking, silently not blocking is the one
  unacceptable failure - hence a test rather than just the fix. It surfaced
  because Python's text mode writes CRLF on Windows.
- **The `check_drift.sh` block asserts the opposite kind of guarantee**: that
  hook never blocks, so its failure mode is reporting the wrong set rather than
  failing open. The tests pin both edges — it must report a changed source, a
  source with no doc at all, and `install.py`; it must stay silent for an
  in-sync tree, for CRLF, for `__pycache__`, and for unlisted root files.
- `test_drift_hook_ignores_crlf_so_a_checkout_is_not_reported_as_drift` is the
  counterpart to the CRLF test above, for a different reason: `.gitattributes`
  stores LF, so a checkout that rewrites a file leaves CRLF in the working tree
  with no content change. Hashing raw bytes reported seven such files at once.
- **`test_drift_hook_does_not_sweep_other_root_files` is why the root list is
  explicit rather than a glob.** The repo root is where throwaway scripts land,
  and a root-level scan reports each as "(no context doc)" — the same noise
  problem the `__pycache__` exclusion already had to solve once.
- Sabotage-verified three ways. Removing `tests/*.py` from `track_dirty.sh`'s
  case statement fails `test_editing_a_test_file_is_tracked` and
  `test_the_same_file_is_only_recorded_once`. Emptying `check_drift.sh`'s
  `root_tracked` fails `test_drift_hook_covers_install_py` and nothing else.
  Replacing that list with a root-level glob fails
  `test_drift_hook_does_not_sweep_other_root_files` and nothing else.

## Dependencies
- Internal: the real scripts in `.claude/hooks/` (read, never modified).
- External: `pytest`; `bash` on PATH — the whole module skips without it, so a
  machine with no bash reports skips rather than failures.

## Open Questions / TODOs
- `explain_commit.sh` (the `Stop` hook that pauses once per landed commit) is
  still uncovered. Its one-shot contract — ack the new sha *before* blocking, so
  one commit never blocks twice — is the part worth a test.
- `check_drift.sh` and `install.py`'s `check_context_docs()` are two
  implementations of one rule. Both are now exercised, but nothing proves they
  *agree*; a test running both over the same fixture tree would.
