#!/usr/bin/env bash
# SessionStart hook: informational-only safety net for changes the PostToolUse hook
# can't see (manual edits outside Edit/Write/NotebookEdit, e.g. via Bash redirects).
# Walks src/, compares each file's sha1 against the source_hash recorded in its
# mirrored context/<path>.md frontmatter, and reports mismatches via
# hookSpecificOutput.additionalContext so the model sees it at session start.
set -euo pipefail

cat >/dev/null # consume stdin (unused)

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
src_dir="$root/src"
ctx_dir="$root/context"

mismatches=()

if [[ -d "$src_dir" ]]; then
  while IFS= read -r -d '' f; do
    rel="${f#$root/}"
    ctxfile="$ctx_dir/$rel.md"
    if [[ -f "$ctxfile" ]]; then
      actual="$(sha1sum "$f" | awk '{print $1}')"
      recorded="$(grep -m1 '^source_hash:' "$ctxfile" | sed 's/^source_hash:[[:space:]]*//' || true)"
      if [[ "$actual" != "$recorded" ]]; then
        mismatches+=("$rel")
      fi
    else
      mismatches+=("$rel (no context doc)")
    fi
  done < <(find "$src_dir" -type f -print0)
fi

if [[ ${#mismatches[@]} -gt 0 ]]; then
  list="$(printf '%s; ' "${mismatches[@]}")"
  esc="$(printf '%s' "$list" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"Context drift detected at session start (source changed without a matching context/<path>.md update, or a context doc is missing) for: %s"},"systemMessage":"Context drift detected for %d file(s) - see additionalContext."}\n' "$esc" "${#mismatches[@]}"
fi
exit 0
