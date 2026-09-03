#!/usr/bin/env bash
# Stop hook: blocks ending the turn while any file in dirty.txt still needs
# something synced - a mirrored context/<path>.md for a src/ file, or a
# requirements.txt/README.md review for pyproject.toml. Blocking is signaled
# by printing {"decision":"block","reason":"..."} on stdout with exit 0 (per
# Claude Code's hook JSON output contract) - the reason text is fed back to
# the model as the instruction for why it must keep going.
set -euo pipefail

cat >/dev/null # consume stdin (unused)

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
dirty="$root/.claude/context_state/dirty.txt"

if [[ -s "$dirty" ]]; then
  src_files=()
  pyproject_flagged=0
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" == "pyproject.toml" ]]; then
      pyproject_flagged=1
    else
      src_files+=("$line")
    fi
  done < "$dirty"

  reason=""
  if [[ ${#src_files[@]} -gt 0 ]]; then
    files="$(printf '%s, ' "${src_files[@]}")"
    files="${files%, }"
    reason+="Context docs are out of sync with source changes. Regenerate context/<path>.md for each of: ${files} (following the template in CLAUDE.md). "
  fi
  if [[ "$pyproject_flagged" -eq 1 ]]; then
    reason+="pyproject.toml changed - regenerate requirements.txt (pip freeze, per the command documented at the top of that file) and review README.md's setup/usage instructions for accuracy. "
  fi
  reason+="Remove each corresponding line from .claude/context_state/dirty.txt once it's handled, then you may stop."

  esc="$(printf '%s' "$reason" | sed 's/\\/\\\\/g; s/"/\\"/g')"
  printf '{"decision":"block","reason":"%s"}\n' "$esc"
fi
exit 0
