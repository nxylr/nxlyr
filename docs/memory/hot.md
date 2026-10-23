# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-23 by memory close-out (task 013, closing tasks 004 and 011). Update at the end of every task._

## State
- Live demo = `main` @ e8998d4 (verify: `git rev-parse --short origin/main`). Public, working.
- F01 shipped (PR #33): `/ws` admits only calls bound by `/demo/call`. Code default `WS_AUTH_MODE=log`; **per the founder, `enforce` is set in the VPS `.env`** (not verified by an agent).
- F02 shipped (PR #35, exit test passed 2026-10-14): `/demo/call` India-only, consent row before dial, per-number/IP/global caps, kill switch `demo:kill`, overrides in `demo:config`. Details: `log.md`, `docs/issues/003-f02-demo-call-lockdown.md`.
- 004 (F09 log hygiene) shipped and verified: PR #38 merged as 51b541c. Batch B (3 calls) and the 011 smoke and exit calls all had zero leaks. Log mechanics: `architecture.md`.
- 011 (F07 turn release) shipped and verified: PR #37 merged as e8998d4, `smart_backstop` with 0.8 s backstop. **Exit test passed 2026-10-23**: 0 of 92 caller turns stalled (baseline 9 of 92), p95 2,428 ms (baseline 4,015). Numbers: `docs/baselines/2026-10-23-011-exit.md`. 011 is complete; backstop stays 0.8 s.
- Open from the exit test: p95/p50 1.88 vs a provisional 1.8, because tool turns pay a second LLM call (median 640 ms). Belongs to 008 and prompt v2.
- Founder decisions for prompt v2 (2026-10-23, detail in `decisions.md`):
  - The bot says it is an AI only when asked, then at once and truthfully, never denying it (pending the lawyer's answer on TRAI and DPDP).
  - The agent is Aarya, female voice.
  - The caller's name comes from a demo-form field now and from lead ingestion later; sir, ma'am or name only is chosen by the visitor or the lead record, never guessed; with no name, the bot never uses one.
- The live site on `main` still has the F10 overclaims; F04, F05, F10, F11 are open. PRs #29–#31 closed unmerged, branches kept.
- Outreach to leads stays paused until the truthful tools, do-not-call and consent work (008, 006, 007) are live; demos that prospects call themselves are fine.
- Merge = deploy. Pushing `main` auto-deploys backend (deploy.yml) and frontend (Vercel).
- Schema: `commitments` + `consents` tables exist in prod (migration file not yet committed to repo).
- KB (`projects.config` for project 1c401a68-…) still promises WhatsApp/brochure sending (F05). Fix SQL prepared, not run.

## In flight
- Task 013 — this memory close-out (004 and 011). In review.
- Worktree `005-docs-specs-research` is open. Cap is 3 open worktrees.

## Next
1. Find why the bot sometimes ends the call after `book_site_visit` (check before prompt v2 and 008 are specced).
2. Prompt v2: spec, then build, including the greeting text (it does not say who is calling or from which company).
3. L1 start-up: a pickup-to-first-audio log line; test with the caller speaking first and with the caller silent.
4. 012: caller name and form of address.
5. 008: truthful tools (write `commitments` rows, real tool results, notification).
6. STT A/B: amounts, and project names as Deepgram key terms.
7. Do-not-call.
8. F05 SQL (founder runs it).
9. Close 005.
10. Three-layer split plan (founder reviewing).

## Backlog (unordered)
`/start` unauthenticated; `WS_AUTH_MODE` code default to `enforce`; KB preload (F06); VPS reboot window (restart required, pending updates); Docker log rotation; GitHub branch protection; `new-task.sh`/`finish-task.sh` worktree footgun; F23 `test_kb_loader` failures; F02 test gaps and the cooldown UX candidate; promote F02 guard into `architecture.md`.

## Human-only pending
- Send Exotel email (DND / 140xx question). Lawyer's answer on TRAI and DPDP (AI disclosure).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Check on the VPS what a `.env` edit does to redis state (`docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Agents never merge. Container logs are scrubbed since 004, but uvicorn's own lines are not: never paste logs unredacted.
- Don't edit the VPS `.env` while calls are in flight (it recreates redis).
- Demo emergency stop, no deploy: `docker compose exec -T redis redis-cli SET demo:kill 1` (clear with `DEL demo:kill`).
- Latency files live in the container and are lost on every deploy: copy them off before deploying.
