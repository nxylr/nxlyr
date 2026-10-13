# Decisions index

Full records in `docs/adr/`. One line each; newest last.

| ADR | Decision | Status |
|---|---|---|
| 0001 | Multi-agent workflow: worktree per task, builder ≠ reviewer, repo is the memory | Accepted 2026-10-13 |
| 0002 | Merge-is-deploy accepted for now; agents never merge; revisit with staging | Accepted 2026-10-13 |

## Standing decisions without an ADR yet
- 2026-10: Keep PRs #29/#30/#31 unmerged to preserve the live demo; founder reads code/schema first.
- 2026-10: F01 (unauthenticated `/ws`) is the first real task under the new workflow. Done 2026-10-13 (PR #33, 7cf8edf).
- 2026-10-13: `/ws` is authenticated by a one-shot Redis binding keyed by the Exotel Call SID (`WS_AUTH_MODE` log→enforce, code default `log`). A handshake token via `CustomField` is an open question, not implemented (spec 001).
- 2026-10-13: Ponytail plugin pinned at 5.2.0 (`https://github.com/DietrichGebert/ponytail.git`, commit `2961b52fc1fe6a5a87c7a959a79512e5c2f3ffe5`). Its hooks auto-activate in Claude Code and are left active on purpose. Do not update it without re-reviewing the hooks.
- 2026-10: Skip OmniRoute (conflicts with provider terms for plan logins). Do not enable the Codex Stop-hook review gate.
