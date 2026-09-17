#!/usr/bin/env bash
# Stop hook: after a commit lands, pause the turn once and make the agent say
# plainly what it committed, then hand the user a compaction prompt.
#
# Why a Stop hook rather than a PostToolUse on `git commit`: the commit is
# usually not the last thing a turn does, and interrupting mid-turn would cut
# across work still in flight. Stop is the point where the agent believes it is
# finished, which is exactly when a summary is worth writing and when dropping
# the accumulated context costs nothing.
#
# **It cannot compact by itself, and does not pretend to.** No hook event or
# output field triggers compaction - PreCompact/PostCompact only *react* to one
# that has already started. So this emits a `systemMessage` asking the user to
# run /compact, which is the nearest thing a hook can do.
#
# One-shot per commit, the same contract as check_pending_commit.sh: the new
# HEAD is acked *before* the block is emitted, so a second Stop for the same
# commit is never blocked twice and the agent can always finish its turn.
set -euo pipefail

cat >/dev/null # consume stdin (unused)

root="${CLAUDE_PROJECT_DIR:-$(pwd)}"
cd "$root"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

head_sha="$(git rev-parse HEAD 2>/dev/null || true)"
[[ -z "$head_sha" ]] && exit 0 # no commits yet

state_dir="$root/.claude/context_state"
mkdir -p "$state_dir"
ack_file="$state_dir/explained_commit.txt"

# First run after this hook was installed: adopt the current HEAD silently.
# Blocking here would demand an explanation of a commit made before the hook
# existed, which the agent may know nothing about.
if [[ ! -f "$ack_file" ]]; then
  printf '%s' "$head_sha" > "$ack_file"
  exit 0
fi

last_sha="$(cat "$ack_file")"
[[ "$head_sha" == "$last_sha" ]] && exit 0 # nothing new committed

# Ack first, block second - see the one-shot note above.
printf '%s' "$head_sha" > "$ack_file"

branch="$(git branch --show-current 2>/dev/null || echo '(detached)')"

# The commits this turn actually added. If the old HEAD is gone (amend, reset,
# rebase), fall back to just the new HEAD rather than failing.
if git cat-file -e "$last_sha" 2>/dev/null; then
  range="$last_sha..$head_sha"
else
  range="-1 $head_sha"
fi
subjects="$(git log --format='  %h  %s' $range 2>/dev/null || true)"
[[ -z "$subjects" ]] && subjects="$(git log -1 --format='  %h  %s' 2>/dev/null || true)"
stat="$(git show --stat --format='' "$head_sha" 2>/dev/null | sed 's/^/  /' | tail -n 12 || true)"
count="$(printf '%s\n' "$subjects" | grep -c . || true)"

reason="A commit landed on branch '$branch' since your last stopping point:

$subjects

Files in the newest commit:
$stat

Before ending this turn, do two things.

1. Tell the user, in your own words and briefly, what you just committed and
   why - what changed, what it fixes or adds, and anything you verified or
   deliberately did not. A few sentences. This is a summary for a human, not a
   replay of the diff, and not a restatement of the commit message they can
   already read above.

2. Then close the turn by telling the user the work is at a clean checkpoint
   and they can run /compact to drop the accumulated context. Do not try to
   compact yourself - no tool or hook can trigger it, only the user can.

This reminder fires once per commit and will not repeat for this one."

json_escape() {
  printf '%s' "$1" | tr -d '\r' \
    | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' \
    | sed -e ':a' -e 'N' -e '$!ba' -e 's/\n/\\n/g'
}

plural="commit"
[[ "$count" -gt 1 ]] && plural="commits"

msg="Checkpoint: $count new $plural on '$branch'. Once the summary lands, /compact is safe to run."

printf '{"decision":"block","reason":"%s","systemMessage":"%s"}\n' \
  "$(json_escape "$reason")" "$(json_escape "$msg")"
exit 0
