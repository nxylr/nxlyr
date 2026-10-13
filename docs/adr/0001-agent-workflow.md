# ADR 0001: Multi-agent workflow — worktree per task, repo as memory

- Status: Accepted
- Date: 2026-10-13
- Deciders: Vansh

## Context
Solo founder using Claude Code (Pro), Codex (Pro), Antigravity (Pro). Agents have no memory between sessions. The live demo runs from `main`, and merging deploys it. Quota is limited, especially Claude Pro.

## Decision
- One task = one spec (`docs/issues/`) = one git worktree (`task/NNN-slug`) = one PR.
- Roles: Claude Code lead (spec, plan, PR report, review), Codex builder, Antigravity QA/UI/docs.
- The agent that wrote the code never reviews it; a different model reviews.
- Every PR carries a 10-heading report, enforced in CI by `pr-report.yml`.
- Memory is files in the repo: `AGENTS.md`, `docs/memory/`, `docs/adr/`. Agents write to `docs/memory/inbox/`; lead promotes.
- Max 3 open worktrees.
- Humans merge; agents never merge or push to `main`.
- Plugins adopted selectively: agent-skills, ponytail, codex-plugin-cc (no review gate). pstack and graphify optional after the core loop works. OmniRoute skipped.

## Alternatives considered
- Single agent on one checkout — context pollution, no independent review.
- Shared long-running agent memory tools — opaque, not reviewable, not versioned.

## Consequences
- Overhead per task (spec + report); worth it because bugs here cost real calls.
- Docs must be kept current: stale memory is worse than none.
- Quota discipline: Claude for short high-leverage steps.
