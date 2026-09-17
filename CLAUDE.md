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

Every file under `src/` and every `.py` under `tests/` has a mirrored context doc
at `context/<path>.md` — e.g.
`src/bookrag/ingest/epub_parser.py` → `context/src/bookrag/ingest/epub_parser.py.md`.
Read the context doc instead of the full source file when you just need to know
what a file does or how it fits together; only open the real source when you're
about to change it or the context doc is insufficient.

**This is hook-enforced, not just a convention to remember:**
- A `PostToolUse` hook (`.claude/hooks/track_dirty.sh`) logs every file under `src/`
  and every `.py` under `tests/` touched via Edit/Write/NotebookEdit into
  `.claude/context_state/dirty.txt` — and also logs `pyproject.toml` itself (see
  below). A non-`.py` file under `tests/` (fixture data) is deliberately not
  tracked: it has no context doc, so blocking on it would be a dead end.
- A `Stop` hook (`.claude/hooks/check_dirty.sh`) blocks the turn from ending while
  that file is non-empty, naming which files still need attention and what kind.
- A `SessionStart` hook (`.claude/hooks/check_drift.sh`) checks, once per session,
  whether any `.py` file under `src/` **or `tests/`** has drifted from the
  `source_hash` recorded in its context doc (catches edits made outside
  Edit/Write, e.g. a manual save) and reports it as informational context — it
  does not block. It hashes CR-stripped content and ignores `__pycache__`.
  This is the safety net for edits the `PostToolUse` hook never saw; the
  blocking path above is the primary enforcement.
- **The two do not cover quite the same set, on purpose.** `check_drift.sh` also
  checks a short list of named root-level files — currently just `install.py`
  (see `root_tracked` in that script, mirrored as `ROOT_TRACKED` in
  `install.py`). `install.py` is the one file that duplicates logic living
  elsewhere: its `check_context_docs()` re-implements `check_drift.sh` for
  contributors not running Claude Code, and it hand-copies `requires-python` and
  `[project.scripts]` from `pyproject.toml`. Nothing else would notice if any of
  those drifted. It is deliberately **not** in `track_dirty.sh`: the risk is
  silent divergence over time, not an unreviewed edit, so editing `install.py`
  does not block a turn — it just gets reported at the next session start, and
  by `install.py` itself on its next run. The root list is explicit rather than a
  scan because the repo root is where throwaway scripts land, and each would
  otherwise be reported as missing a doc. See `tests/test_hooks.py`.
- `install.py` runs the same check (`--skip-doc-check` opts out), so a
  contributor not using Claude Code still sees stale docs. The hook stays
  authoritative; keep the two consistent if either changes.

**So: whenever you create or edit a file under `src/` — or a `.py` under
`tests/` — before ending your turn, update its `context/<path>.md` and update
`context/_INDEX.md` if the file's one-line purpose changed** — the Stop hook
will otherwise block you and tell you exactly which files are pending.

Adding a test counts. The most likely stale doc is one describing behaviour a
*renamed* test used to cover: the rename looks harmless, and the prose
describing the old behaviour survives it.

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
**Get the hash with `tr -d '\r' < <file> | sha1sum`** (Git Bash) — the CR strip
is not optional. `.gitattributes` is `* text=auto eol=lf`, so git stores every
file with LF and any checkout that rewrites a file gives the working tree LF,
while a file newly written on Windows may be CRLF. A hash taken from raw bytes
therefore goes stale the moment a checkout normalizes the file, with no content
change at all — that is what silently invalidated seven context docs when a
`git checkout master`/merge rewrote files during a push, and it accounted for
most of a "pre-existing stale docs" backlog that turned out not to exist.
`check_drift.sh` and `install.py` both strip CRs before hashing, so recording a
raw-byte hash of a CRLF file is what breaks, not the other way round.

## Project layout
```
install.py          one-step installer (venv + deps + .env + Ollama check).
                     Stdlib-only and deliberately 3.6-parseable, so a
                     too-old interpreter gets a readable message rather than
                     a SyntaxError. Not under src/, so not tracked by
                     track_dirty.sh - but it does have context/install.py.md
                     and check_drift.sh watches it. See above for why the two
                     hooks treat it differently.
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

**Keep the history linear. Never create a merge commit.** When the user does
approve a release, fast-forward:

```
git push origin development:master    # then, locally:
git checkout master && git merge --ff-only development && git checkout development
```

`--no-ff` was used once (`febb954`) and is the thing to avoid. It leaves
`master` and `development` pointing at *different commits with byte-identical
trees*, permanently, and adds one such commit per release — needless divergent
state whose only payoff is a summary message that belongs in the individual
commits anyway. If a fast-forward is ever refused, that means `master` has
genuinely moved and the right response is to ask the user, not to reach for
`--no-ff` or `--force`.

**Run the test suite once, before the release, on `development`.** Re-running
it after a fast-forward tests byte-identical content and proves nothing — the
trees are the same by definition. The only case that warrants a second run is
a merge that was *not* a fast-forward, which under the rule above should not
happen without asking first.

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
- A second `Stop` hook (`.claude/hooks/explain_commit.sh`) closes the loop on
  the other side: once a commit has actually landed, it blocks the turn once
  and requires a plain-language summary of what was committed and why, then
  tells the user the work is at a clean checkpoint they can `/compact` from.
  It tracks `HEAD` in `.claude/context_state/explained_commit.txt`, acks the
  new sha *before* blocking (so one commit never blocks twice), and adopts the
  current `HEAD` silently on first run rather than demanding an explanation of
  history that predates it.

  **It cannot compact, and deliberately doesn't pretend to.** No hook event or
  output field triggers compaction — `PreCompact`/`PostCompact` only *react* to
  one already under way — so it emits a `systemMessage` asking the user to run
  `/compact`. If that ever changes, this is the hook to revisit.

  It is a `Stop` hook rather than a `PostToolUse` on `git commit` because a
  commit is usually not the last thing a turn does; interrupting at the commit
  itself would cut across work still in flight, whereas `Stop` is the point
  where the turn is believed finished and dropping context costs nothing.
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
