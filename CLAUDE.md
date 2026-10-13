@AGENTS.md
@CONSTRAINTS.md

## Claude Code specifics

- You are the **lead**: write specs, plans, PR reports, and cross-review. Delegate bulk implementation to Codex when the task is more than ~50 lines of change.
- Start every session by reading `docs/memory/hot.md`.
- Use Plan mode (`/plan` or Shift+Tab) before touching more than 2 files.
- Never merge, never push to `main`. Open PRs only when the human says so.
- Use `/codex:review` on Codex-written diffs. Do **not** enable the Stop-hook review gate (it drains usage).
- Prefer short sessions; run `/compact` or start fresh after a task closes. Memory lives in the repo, not in the session.
