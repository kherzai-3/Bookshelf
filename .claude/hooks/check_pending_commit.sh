#!/usr/bin/env bash
# Stop hook: reminds (once per distinct change-set, never on every turn) to
# commit a completed piece of work to the `development` branch, per CLAUDE.md's
# git workflow convention. Deliberately does NOT try to judge "is this a major
# change" or "have tests passed" - a hook can't know that. It only detects that
# something changed and hasn't been flagged yet, then leaves the actual
# judgment call (commit now vs. keep going) to the model. Runs after
# check_dirty.sh's concern is resolved - no point suggesting a commit while
# context docs are still known to be out of sync.
set -euo pipefail

cat >/dev/null # consume stdin (unused)

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$root"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

dirty="$root/.claude/context_state/dirty.txt"
[[ -s "$dirty" ]] && exit 0 # check_dirty.sh already owns this turn's block reason

status="$(git status --porcelain 2>/dev/null || true)"
[[ -z "$status" ]] && exit 0 # nothing uncommitted - also naturally resets after any commit

current_hash="$(printf '%s' "$status" | sha1sum | awk '{print $1}')"

state_dir="$root/.claude/context_state"
mkdir -p "$state_dir"
ack_file="$state_dir/commit_reminder_ack.txt"

last_hash=""
[[ -f "$ack_file" ]] && last_hash="$(cat "$ack_file")"
[[ "$current_hash" == "$last_hash" ]] && exit 0 # already reminded for this exact state

# Record the ack *before* emitting the block, so a second Stop attempt for this
# same change-set (e.g. the model judges it's genuinely still in progress) is
# never blocked twice - this is a one-shot reminder, not a recurring gate.
printf '%s' "$current_hash" > "$ack_file"

branch="$(git branch --show-current 2>/dev/null || true)"
count="$(printf '%s\n' "$status" | grep -c . || true)"

reason="You have $count uncommitted file(s) on branch '$branch'. If this represents the logical conclusion of a bug fix, rewrite, or new feature - context docs synced, tests passing - commit it now to the development branch per CLAUDE.md's git convention (never master, never a push, without explicit user instruction each time). If this work is genuinely still in progress, no action is needed - this reminder will not repeat until the change-set changes further."

esc="$(printf '%s' "$reason" | sed 's/\\/\\\\/g; s/"/\\"/g')"
printf '{"decision":"block","reason":"%s"}\n' "$esc"
exit 0
