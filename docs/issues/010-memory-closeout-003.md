---
name: Task spec
title: "010: Memory close-out for task 003 (F02)"
labels: task, docs
---

## Goal
Close out task 003 per AGENTS.md step 9: record the F02 outcome and exit-test evidence in `docs/memory/log.md` and `hot.md`, and split the F02 inbox note into one fact per file with live-verified sources.

## Files in scope
- `docs/memory/hot.md`, `docs/memory/log.md`
- `docs/memory/inbox/` (split `2026-10-14-f02-demo-call-guard.md` into three notes)
- `docs/issues/010-memory-closeout-003.md`

## Out of scope
- Any change under `agent/`, `dashboard/`, `infra/`, `.github/`, `supabase/`, `scripts/`.
- Promoting the inbox notes into `architecture.md` / `product.md` / `decisions.md` (lead, separately; `architecture.md` still lists F02 as open).

## Acceptance criteria
- [ ] `hot.md` is under 60 lines, live SHA is 870482a, F02 recorded as shipped, and spec step 7 recorded as wrong with the code right.
- [ ] `log.md` has the F02 build, merge, exit-test evidence, observations, and what is not proven live; no phone numbers, IPs, logs or secrets.
- [ ] The old inbox note is gone; three notes each hold one fact with a source; unverified claims are marked UNVERIFIED.

## Exit test
- 🧑 Read the diff; merge when happy. No deploy effect beyond a docs-only push to `main`.

## Builder / Reviewer
- Builder: claude (docs only)
- Reviewer: human reads the diff.
