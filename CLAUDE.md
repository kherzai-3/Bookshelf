# Book_RAG

> This file is standing instructions for an AI coding agent working in this
> repo. A human contributor should start with `README.md`; come back here
> for the enforced context-doc and git conventions below.

RAG tool that ingests `.epub`/`.pdf` novels and builds a queryable, spoiler-safe
catalog of characters, settings, and themes — each tracked with chapter-scoped
history so a reference to chapter N never leaks what happens after it.

Stack: Python (`src/bookrag/`), local single-user, pluggable LLM backends
(local models via Ollama by default, swappable to Claude via the Anthropic
API) with an eval harness to compare their output.

## Context-file convention (read this before editing any source file)

Every file under `src/` has a mirrored context doc at `context/<path>.md` — e.g.
`src/bookrag/ingest/epub_parser.py` → `context/src/bookrag/ingest/epub_parser.py.md`.
Read the context doc instead of the full source file when you just need to know
what a file does or how it fits together; only open the real source when you're
about to change it or the context doc is insufficient.

**This is hook-enforced, not just a convention to remember:**
- A `PostToolUse` hook (`.claude/hooks/track_dirty.sh`) logs every file under `src/`
  touched via Edit/Write/NotebookEdit into `.claude/context_state/dirty.txt` —
  and also logs `pyproject.toml` itself (see below).
- A `Stop` hook (`.claude/hooks/check_dirty.sh`) blocks the turn from ending while
  that file is non-empty, naming which files still need attention and what kind.
- A `SessionStart` hook (`.claude/hooks/check_drift.sh`) checks, once per session,
  whether any `src/` file's hash has drifted from the `source_hash` recorded in its
  context doc (catches edits made outside Edit/Write, e.g. a manual save) and
  reports it as informational context — it does not block.

**So: whenever you create or edit a file under `src/`, before ending your turn,
update its `context/<path>.md` and update `context/_INDEX.md` if the file's
one-line purpose changed** — the Stop hook will otherwise block you and tell you
exactly which files are pending.

**Editing `pyproject.toml` (dependencies or `[project.scripts]`) is tracked the
same way**, but the required follow-up is different: regenerate `requirements.txt`
(command is documented at the top of that file) and review `README.md`'s
setup/usage instructions for accuracy, since both describe what `pyproject.toml`
declares. `README.md`/`requirements.txt` edits themselves are not tracked — only
the `pyproject.toml` change that motivates them is.

### Per-file context doc template
```
---
source: <relative path to the real file>
last_synced: <ISO 8601 timestamp>
source_hash: <sha1sum of the source file>
---

## Purpose
Why this file exists, one paragraph.

## Public Interface
Functions/classes/CLI entry points this file exposes, one line each.

## Key Decisions
Non-obvious choices and why (omit if nothing would surprise a reader).

## Dependencies
- Internal: other project files this imports/depends on
- External: third-party packages this relies on

## Data Contracts
Shapes of data in/out (schemas, dataclasses, DB rows), if any.

## Open Questions / TODOs
Unresolved items, deliberately deferred decisions.
```
Omit sections that don't apply (a pure config file has no "Public Interface").
Get the hash with `sha1sum <file>` (Git Bash).

## Project layout
```
src/bookrag/        Python package: ingest/ (epub/pdf -> Chapter), storage.py
                     (data/library/ persistence), cli.py (`bookrag ingest ...`)
context/            mirrored context docs, see above
data/incoming/       suggested (not enforced) staging spot for books not yet ingested.
data/library/        ingested books live here: <book_id>/{source.*, metadata.json,
                     chapters.jsonl} + index.json. Gitignored - not source, not
                     context-hook-tracked.
.claude/hooks/       the enforcement scripts (bash - no Python/Node/jq on this
                     machine when they were written, so they stay bash even
                     though the package itself now uses Python)
```

## Git workflow convention

Work happens on the `development` branch. Commit a completed piece of work —
a bug fix, a rewrite of an existing file, a new feature — at its **logical
conclusion**: once its context docs are synced (see above) and the test suite
passes. Don't commit mid-implementation, and don't wait to batch up multiple
unrelated changes into one commit either — one commit per completed change,
with a message that explains why, not just what.

**Never merge `development` into `master`, and never push to any remote,
without the user explicitly instructing it in that specific instance.** A
past approval of one merge/push does not carry forward to the next one — this
matches the project's general "confirm before hard-to-reverse or shared-state
actions" policy, applied specifically to this repo's branch model. `master`
is the user's checkpoint of record; only they decide when `development`'s
state is ready to become it.

**Partially hook-enforced, the same way the context-doc convention is:**
- A `Stop` hook (`.claude/hooks/check_pending_commit.sh`) notices when
  `git status` shows uncommitted changes and reminds about this convention —
  but only once per distinct change-set (it hashes `git status --porcelain`
  and acks it immediately, so re-running Stop for the same still-in-progress
  change never blocks twice). It deliberately cannot judge "is this actually
  done" or "did tests pass" — that judgment call stays with the agent, not
  the hook; the hook only guarantees the reminder surfaces at least once
  per real change.
- It stays silent while `.claude/context_state/dirty.txt` is non-empty —
  no point suggesting a commit before `check_dirty.sh`'s own concern
  (context docs out of sync) is resolved.
- There is deliberately no hook that blocks a `master` merge or a push - a
  hook can't distinguish "the user just asked for this" from "the model
  decided to do this on its own," so that distinction has to stay a judgment
  call too, governed by this section rather than mechanically enforced.

## Series / chapter identity
Chapters are always addressed as `(book_id, chapter_index)`, never a bare
chapter number. Two books in the same series can each have their own
"chapter 2" without collision, because each book gets its own directory and
its own `chapters.jsonl`. A book's `series` metadata (`{name, position}`) is
a pure grouping signal for later cross-book work (e.g. a character catalog
spanning a series) - it must never cause two books' chapters to be merged
into one numbering space. See `tests/test_storage.py::
test_series_books_each_keep_their_own_chapter_2`.
