#!/usr/bin/env bash
# Create the GitHub labels used by the workflow. Needs: gh auth login (done by the human).
set -euo pipefail

mk() { gh label create "$1" --color "$2" --description "$3" --force; }

mk task            0E8A16 "One spec = one worktree = one PR"
mk needs-human     D93F0B "Blocked on a human-only step"
mk needs-review    FBCA04 "Waiting for cross-model review"
mk real-test-pending B60205 "Merged-ready but exit test not yet run on real system"
mk audit           5319E7 "From the independent audit (F01-F26)"
mk builder:codex   1D76DB "Built by Codex"
mk builder:claude  1D76DB "Built by Claude Code"
mk builder:antigravity 1D76DB "Built by Antigravity"

echo "labels ready"
