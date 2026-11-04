---
name: Task spec
title: "024: Memory close-out for tasks 022 (barge-in) and 021 (multilingual)"
labels: task, docs
---

## Goal
Close out tasks 022 and 021 per AGENTS.md step 9: record what shipped, the live settings and the exit results in `docs/memory/`, promote the inbox notes they resolved, and park the follow-ups. Exit results are per the founder, not verified by an agent.

## Files in scope
- `docs/memory/hot.md`, `log.md`, `architecture.md`, `decisions.md`, `patterns.md`, `mistakes.md`
- `docs/memory/inbox/` (promote then delete resolved notes; one-line updates to notes that stay)
- `docs/issues/024-memory-closeout-021-022.md`
- `AGENTS.md` only if the test command or count is wrong (checked: 15 modules, 266 tests, already correct)

## Out of scope
- Anything under `agent/`, `dashboard/`, `infra/`, `.github/`, `supabase/`, `scripts/`.
- The 023 worktree (paused, uncommitted design work).
- `product.md` (no public claim is changed by this close-out).

## Acceptance criteria
- [ ] `hot.md` is under 60 lines: shipped work, live commit 7b0254a, live settings, "technical work paused for founder decisions; 023 design waiting in its worktree", and the seven parked items in Next.
- [ ] `log.md` has one dated entry per task (022, 021) with the founder's results, and every result is marked "per the founder, not verified by an agent".
- [ ] Facts added to `architecture.md`, `decisions.md`, `patterns.md`, `mistakes.md` only where relevant, each checked against the code or marked as the founder's report.
- [ ] Resolved inbox notes are promoted and deleted; unresolved ones stay.
- [ ] The full test command runs: 266 tests, 15 modules, OK.

## Exit test
- 🧑 Read the diff; merge when happy. A docs-only merge still redeploys (`deploy.yml` has no path filter).

## Builder / Reviewer
- Builder: claude (docs only)
- Reviewer: human reads the diff.
