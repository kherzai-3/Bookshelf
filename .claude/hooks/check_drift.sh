#!/usr/bin/env bash
# SessionStart hook: informational-only safety net for changes the PostToolUse hook
# can't see (manual edits outside Edit/Write/NotebookEdit, e.g. via Bash redirects).
# Walks src/ and tests/, compares each file's sha1 against the source_hash recorded
# in its mirrored context/<path>.md frontmatter, and reports mismatches via
# hookSpecificOutput.additionalContext so the model sees it at session start.
#
# Three things this deliberately does, each from a real false result:
#
# 1. It hashes CR-stripped content. .gitattributes is `* text=auto eol=lf`, so git
#    stores LF and any checkout that rewrites a file leaves the working tree with
#    LF, while a file newly written on Windows may be CRLF. Hashing raw bytes made
#    a `git checkout` report drift on files whose content had not changed at all -
#    seven at once on 2026-09-13, which is most of what the "pre-existing context
#    drift" backlog item turned out to be. Whoever records a source_hash must strip
#    CRs the same way: `tr -d '\r' < <file> | sha1sum`.
# 2. It walks tests/ as well as src/. The convention covers both, but only src/ was
#    ever checked, so ten test context docs drifted unnoticed.
# 3. It only looks at files that can actually have a context doc - no __pycache__,
#    no .pyc. Those produced a wall of "(no context doc)" noise that buried the
#    real findings.
#
# Still informational only: it never blocks. Blocking stays with check_dirty.sh.
set -euo pipefail

cat >/dev/null # consume stdin (unused)

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
ctx_dir="$root/context"

mismatches=()

for dir in src tests; do
  target="$root/$dir"
  [[ -d "$target" ]] || continue
  while IFS= read -r -d '' f; do
    rel="${f#"$root"/}"
    ctxfile="$ctx_dir/$rel.md"
    if [[ -f "$ctxfile" ]]; then
      actual="$(tr -d '\r' < "$f" | sha1sum | awk '{print $1}')"
      recorded="$(grep -m1 '^source_hash:' "$ctxfile" | sed 's/^source_hash:[[:space:]]*//' || true)"
      if [[ "$actual" != "$recorded" ]]; then
        mismatches+=("$rel")
      fi
    else
      mismatches+=("$rel (no context doc)")
    fi
  done < <(find "$target" -type f -name '*.py' -not -path '*/__pycache__/*' -print0)
done

if [[ ${#mismatches[@]} -gt 0 ]]; then
  list="$(printf '%s; ' "${mismatches[@]}")"
  esc="$(printf '%s' "$list" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Context drift detected at session start (source changed without a matching context/<path>.md update, or a context doc is missing) for: %s"},"systemMessage":"Context drift detected for %d file(s) - see additionalContext."}\n' "$esc" "${#mismatches[@]}"
fi
exit 0
