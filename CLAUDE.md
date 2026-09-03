# Book_RAG

RAG tool that ingests `.epub`/`.pdf` novels and builds a queryable, spoiler-safe
catalog of characters, settings, and themes — each tracked with chapter-scoped
history so a reference to chapter N never leaks what happens after it.

Stack: Python (`src/bookrag/`), local single-user, pluggable LLM backends
(Claude via Anthropic API by default, swappable to a local model) with an eval
harness to compare their output.

## Context-file convention (read this before editing any source file)

Every file under `src/` has a mirrored context doc at `context/<path>.md` — e.g.
`src/bookrag/ingest/epub_parser.py` → `context/src/bookrag/ingest/epub_parser.py.md`.
Read the context doc instead of the full source file when you just need to know
what a file does or how it fits together; only open the real source when you're
about to change it or the context doc is insufficient.

**This is hook-enforced, not just a convention I need to remember:**
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
.claude/hooks/       the three enforcement scripts (bash - no Python/Node/jq on
                     this machine when they were written, so they stay bash even
                     though the package itself now uses Python)
```

## Series / chapter identity
Chapters are always addressed as `(book_id, chapter_index)`, never a bare
chapter number. Two books in the same series can each have their own
"chapter 2" without collision, because each book gets its own directory and
its own `chapters.jsonl`. A book's `series` metadata (`{name, position}`) is
a pure grouping signal for later cross-book work (e.g. a character catalog
spanning a series) - it must never cause two books' chapters to be merged
into one numbering space. See `tests/test_storage.py::
test_series_books_each_keep_their_own_chapter_2`.
