---
source: tests/test_hooks.py
last_synced: 2026-09-13T17:30:00Z
source_hash: 254eba0aa12758b4dbc81126463086a2d00259c1
---

## Purpose
Covers the context-doc enforcement hooks themselves (`track_dirty.sh`,
`check_dirty.sh`). They are bash rather than part of the package and had no
coverage at all — which is how `tests/` stayed detected-but-not-blocked long
enough for eleven test context docs to drift unnoticed. The rule they
implement is a project guarantee, so it is tested like any other.

## Public Interface
- `run_hook(name, payload, root)` — runs a real hook script against a
  throwaway project root, via `CLAUDE_PROJECT_DIR`.
- `track(root, edited)` — runs `track_dirty.sh` for an edit to `edited` and
  returns the resulting `dirty.txt` lines.

## Key Decisions
- **Every test uses `tmp_path` as the project root**, so running the suite can
  never write to this repo's own `.claude/context_state/dirty.txt`. A test that
  polluted the real dirty file would block the turn that ran it.
- **What must be tracked**: `.py` under `tests/` (the guarantee this exists
  for), anything under `src/`, and `pyproject.toml`. **What must not**: a
  non-`.py` fixture file under `tests/` (no context doc exists for it, so
  blocking would be a dead end), a `__pycache__` artifact, a file outside both
  directories, and a file outside the project entirely.
- `test_stop_hook_still_emits_valid_json_for_a_crlf_dirty_file` covers a real
  bug this module found: a CR reaching the reason string made the hook's JSON
  unparseable, so the block decision was dropped and the hook failed **open**.
  For a hook whose entire job is blocking, silently not blocking is the one
  unacceptable failure - hence a test rather than just the fix. It surfaced
  because Python's text mode writes CRLF on Windows.
- Sabotage-verified: removing `tests/*.py` from `track_dirty.sh`'s case
  statement fails `test_editing_a_test_file_is_tracked` and
  `test_the_same_file_is_only_recorded_once`.

## Dependencies
- Internal: the real scripts in `.claude/hooks/` (read, never modified).
- External: `pytest`; `bash` on PATH — the whole module skips without it, so a
  machine with no bash reports skips rather than failures.

## Open Questions / TODOs
- `check_drift.sh` (the `SessionStart` safety net) is not covered here; only
  the blocking path is. Its logic is checked indirectly by `install.py`'s
  equivalent implementation being verified against it by hand.
