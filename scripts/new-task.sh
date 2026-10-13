#!/usr/bin/env bash
# Create a fresh worktree + branch for one task, from up-to-date origin/main.
# Usage: scripts/new-task.sh 001-f01-authenticate-ws
set -euo pipefail

SLUG="${1:-}"
if [[ -z "$SLUG" ]]; then
  echo "usage: scripts/new-task.sh NNN-slug" >&2
  exit 1
fi
if [[ ! "$SLUG" =~ ^[0-9]{3}-[a-z0-9-]+$ ]]; then
  echo "slug must look like 001-some-name (3 digits, lowercase, dashes)" >&2
  exit 1
fi

ROOT="$(git rev-parse --show-toplevel)"
BASE="$(dirname "$ROOT")/nxlyr-worktrees"
DIR="$BASE/$SLUG"
BRANCH="task/$SLUG"

if [[ -e "$DIR" ]]; then
  echo "worktree already exists: $DIR" >&2
  exit 1
fi
if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  echo "branch already exists: $BRANCH" >&2
  exit 1
fi

# cap open worktrees at 3 (excluding the main checkout)
OPEN="$(git -C "$ROOT" worktree list --porcelain | grep -c '^worktree ' || true)"
if (( OPEN - 1 >= 3 )); then
  echo "already $((OPEN - 1)) task worktrees open (cap is 3). Finish one first:" >&2
  git -C "$ROOT" worktree list >&2
  exit 1
fi

mkdir -p "$BASE"
git -C "$ROOT" fetch origin main
git -C "$ROOT" worktree add -b "$BRANCH" "$DIR" origin/main

echo
echo "Worktree ready: $DIR"
echo "Branch:         $BRANCH (from origin/main $(git -C "$DIR" rev-parse --short HEAD))"
if [[ -f "$DIR/docs/issues/$SLUG.md" ]]; then
  echo "Spec:           docs/issues/$SLUG.md"
else
  echo "Spec:           MISSING docs/issues/$SLUG.md  <- write and approve the spec before building"
fi
echo
echo "Next: cd \"$DIR\" and start the builder agent there."
