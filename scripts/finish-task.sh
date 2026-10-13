#!/usr/bin/env bash
# Remove a task worktree after its PR is merged (or abandoned).
# Usage: scripts/finish-task.sh 001-f01-authenticate-ws
set -euo pipefail

SLUG="${1:-}"
if [[ -z "$SLUG" ]]; then
  echo "usage: scripts/finish-task.sh NNN-slug" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
DIR="$(dirname "$ROOT")/nxlyr-worktrees/$SLUG"
BRANCH="task/$SLUG"

if [[ ! -d "$DIR" ]]; then
  echo "no worktree at $DIR" >&2
  exit 1
fi

if [[ -n "$(git -C "$DIR" status --porcelain)" ]]; then
  echo "worktree has uncommitted changes — commit, stash or discard them first:" >&2
  git -C "$DIR" status --short >&2
  exit 1
fi

git -C "$ROOT" fetch origin main --quiet

if git -C "$ROOT" merge-base --is-ancestor "$BRANCH" origin/main 2>/dev/null; then
  echo "Branch $BRANCH is merged into origin/main."
  MERGED=1
else
  echo "WARNING: $BRANCH is NOT merged into origin/main (squash merges also look unmerged)."
  read -r -p "Remove the worktree anyway? Branch is kept. [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted"; exit 1; }
  MERGED=0
fi

git -C "$ROOT" worktree remove "$DIR"
echo "Removed worktree $DIR"

if (( MERGED == 1 )); then
  git -C "$ROOT" branch -d "$BRANCH" || true
else
  echo "Branch $BRANCH kept. Delete later with: git branch -D $BRANCH"
fi

echo
echo "Memory check: did you add docs/memory/inbox/ notes for this task? (AGENTS.md step 9)"
