---
name: Task spec
title: "002: Memory close-out for task 001 (F01)"
labels: task, docs
---

## Goal
Close out task 001 per AGENTS.md step 9: promote its inbox notes into `docs/memory/`, correct stale facts, fix the commands that did not work from a worktree, and stop `new-task.sh` from setting task branches to track `origin/main`.

## Files in scope
- `docs/memory/` (hot, architecture, decisions, mistakes, patterns, log) and `docs/memory/inbox/`
- `AGENTS.md` ("Commands" section only)
- `scripts/new-task.sh` (`--no-track` only)
- `docs/issues/002-memory-closeout-001.md`

## Out of scope
- Any change under `agent/`, `dashboard/`, `infra/`, `.github/`, `supabase/`.
- Fixing F23 (`test_kb_loader` errors), authenticating `/start`, or changing `finish-task.sh`.

## Acceptance criteria
- [ ] Promoted inbox notes are deleted; the one unverified note (`env-edit-recreates-redis`) stays in the inbox with its claims marked UNVERIFIED.
- [ ] `hot.md` is under 60 lines, live SHA is 7cf8edf, and anything not verified by an agent is marked as reported.
- [ ] AGENTS.md Commands work from a worktree (verified by running them).
- [ ] A branch created by `new-task.sh` has no upstream.

## Exit test
- 🤖 Run the AGENTS.md test and import-smoke commands from the worktree; create and finish a throwaway task and check `git config branch.<name>.merge` is empty.
- 🧑 Read the diff; merge when happy.

## Builder / Reviewer
- Builder: claude (docs/script only, small change)
- Reviewer: human reads the diff (no code under `agent/`).
