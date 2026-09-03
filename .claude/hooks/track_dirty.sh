#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|NotebookEdit): records any touched file under src/,
# or pyproject.toml itself, into .claude/context_state/dirty.txt so check_dirty.sh
# can enforce a sync before the turn is allowed to end - a context/<path>.md
# regeneration for src/ files, or a requirements.txt/README.md review for
# pyproject.toml (its dependencies/entry points are what those two describe).
# No jq/node/python available on this machine, so JSON extraction is done with
# grep/sed against the known flat tool_input shape.
set -euo pipefail

input="$(cat)"

extract_field() {
  printf '%s' "$input" | grep -o "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" | head -1 \
    | sed -E "s/^\"$1\"[[:space:]]*:[[:space:]]*\"//; s/\"\$//" || true
}

raw_path="$(extract_field file_path)"
if [[ -z "$raw_path" ]]; then
  raw_path="$(extract_field notebook_path)"
fi
[[ -z "$raw_path" ]] && exit 0

# JSON escapes a Windows path separator as two backslashes; collapse to a forward slash.
path="$(printf '%s' "$raw_path" | sed 's/\\\\/\//g')"

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
root="${root//\\//}"
root="${root%/}"

root_lc="${root,,}"
path_lc="${path,,}"
if [[ "$path_lc" != "$root_lc"/* ]]; then
  exit 0
fi
rel="${path:${#root}+1}"

case "$rel" in
  src/*|pyproject.toml) ;;
  *) exit 0 ;;
esac

state_dir="$root/.claude/context_state"
mkdir -p "$state_dir"
dirty="$state_dir/dirty.txt"
touch "$dirty"
if ! grep -qxF "$rel" "$dirty" 2>/dev/null; then
  echo "$rel" >> "$dirty"
fi
exit 0
