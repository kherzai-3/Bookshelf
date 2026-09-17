---
source: install.py
last_synced: 2026-09-17T16:02:00Z
source_hash: 0d2ea2fe04656a106f618f58ebde38cb9ab05895
---

## Purpose
One-step installer: `python install.py` takes a fresh clone to a working
checkout — creates `.venv`, installs pinned dependencies, installs `bookrag`
itself editable, seeds `.env` and `data/`, checks the context docs, and reports
on the optional Ollama runtime. Every step is idempotent, so it doubles as the
"pull latest and re-install" command.

It lives at the repo root rather than under `src/` because it must run *before*
the package exists, with nothing but the standard library available.

## Public Interface
CLI, not an importable module:
- `python install.py` — the whole sequence.
- `--recreate` — delete and rebuild `.venv` from scratch.
- `--model NAME` — which Ollama model to check for (default: whatever the
  freshly-installed `bookrag` uses).
- `--pull-model` / `--no-pull-model` — download the model without asking, or
  never ask.
- `--skip-ollama` — skip the runtime check entirely.
- `--run-tests` — run pytest after installing.
- `--skip-doc-check` — skip the context-doc freshness check.

Exit codes: `0` on success (warnings are collected and reprinted, never fatal),
`1` on a hard failure, `130` on Ctrl-C.

## Key Decisions
- **Python-3.6-parseable syntax, despite the project requiring 3.11+.** No
  annotations, no walrus, no f-strings. A too-old interpreter must reach
  `check_python()` and print a readable version message rather than die with a
  `SyntaxError` from a construct it cannot parse. Deliberate, not oversight.
- **Pure-ASCII output.** A Windows cp1252 console mangles non-ASCII, and an
  installer printing mojibake on its first line looks broken before it starts.
- **Never installs Ollama and never installs Python.** Both are out of scope for
  a script that needs one of them already running to execute at all.
- **`default_model()` asks the installed package for `DEFAULT_MODEL`** rather
  than hardcoding it, so this script cannot recommend pulling a model the tool
  no longer defaults to. The module-level `DEFAULT_OLLAMA_MODEL` exists only
  because argparse builds its help text before anything is installed.
- **The pinned lock is tried twice before falling back.** `requirements.txt` was
  frozen on one machine, so its exact versions may have no wheel elsewhere;
  `pyproject.toml`'s dependency groups always resolve. The retry exists because
  the first real failure was transient (a network hiccup), and falling back on
  one bad attempt would trade a pinned install for an unpinned one over nothing.
  Which path was used is always stated — a silent fallback would quietly cost
  the reproducibility the lock exists for.
- **Ollama is reached over HTTP, never via the `ollama` CLI.** Real case on this
  project's own Windows machine: the binary is not on `PATH` under Git Bash, yet
  the server answers fine. The HTTP API is reachable under exactly the condition
  `bookrag` itself needs, so it is the honest thing to test.
- **`should_pull` catches `EOFError` as well as checking `isatty()`.** On
  Windows, stdin redirected from `NUL` reports as a tty because `NUL` is a
  character device, so a non-interactive run can still reach the prompt.
- **`report_placement` reads `/api/ps` and stays quiet when nothing is loaded**,
  rather than forcing a multi-GB model load during an install to answer a
  question `bookrag extract` answers for free after its first chapter.
- **`print_next_steps()` double-quotes the example path.** Book filenames
  routinely contain apostrophes, and an unquoted one leaves PowerShell at a `>>`
  continuation prompt that looks exactly like a hang. That line is the first
  command a new user copies. (Same defect as papercut P2.)

## Dependencies
- Internal: none at import time — stdlib only, by design. It *invokes* the
  installed `bookrag` (`-m bookrag.cli --help`, and
  `providers.ollama_provider.DEFAULT_MODEL`) after installing it.
- External: none. `argparse`, `json`, `os`, `shutil`, `subprocess`, `sys`, plus
  `hashlib` and `urllib.request` imported locally where used.
- Reads: `pyproject.toml`, `requirements.txt`, `.env.example`, `context/**.md`.
- Writes: `.venv/`, `.env` (only if absent), `data/incoming/`, `data/library/`.

## Data Contracts
- `check_context_docs()` parses `source_hash:` out of each `context/<path>.md`
  frontmatter and compares it to `sha1(CR-stripped file bytes)`. This must stay
  byte-for-byte equivalent to `.claude/hooks/check_drift.sh` — see below.
- `ROOT_TRACKED = ("install.py",)` must stay identical to `check_drift.sh`'s
  `root_tracked` array.

## Why this file has a context doc at all
It is the **only file outside `src/` and `tests/` that carries one**, and it was
added on 2026-09-17 for a specific reason: this file duplicates logic that lives
elsewhere, and nothing was watching the copies.

- `check_context_docs()` is a second implementation of `check_drift.sh`, for
  contributors not running Claude Code. `CLAUDE.md` says to keep the two
  consistent; that was a written rule with no enforcement behind it.
- `MIN_PYTHON = (3, 11)` hand-copies `pyproject.toml`'s `requires-python`.
- `venv_bin("bookrag")`, `-m bookrag.cli` and the literal `ingest` string in
  `verify_install()` hand-copy `[project.scripts]` and the CLI's own surface.

All of those agree today. The risk is silent divergence over time, which is a
*change-detection* problem, not an unreviewed-edit problem — so this file is
covered by `check_drift.sh` (informational, once per session) and deliberately
**not** added to `track_dirty.sh` (which blocks the turn on every edit). Editing
install.py does not block; changing it without updating this doc gets reported
at the next session start, and by `install.py` itself on the next run.

The check is pleasantly recursive: `install.py` verifies its own context doc.

## Open Questions / TODOs
- `check_context_docs()` and `check_drift.sh` are still two implementations of
  one rule. The drift check now *notices* when either changes, but nothing
  proves they agree — a test that ran both over the same fixture tree would.
- `.env` is seeded from `.env.example` and then never reconciled: a variable
  added to the example later does not appear in an existing `.env`. Harmless
  today because every setting is optional and a blank value counts as unset
  (`env.env_str`), but it would not survive a required setting being added.
