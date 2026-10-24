# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-24 by memory close-out (task 017, closing task 015). Update at the end of every task._

## State
- Live demo = `main`; last code change 8b21625 (task 015, PR #42); later merges are docs-only but still redeploy. Verify: `git rev-parse --short origin/main`. Public, working.
- F01 shipped (PR #33): `/ws` admits only calls bound by `/demo/call`. Code default `WS_AUTH_MODE=log`; **per the founder, `enforce` is set in the VPS `.env`** (not verified by an agent).
- F02 shipped (PR #35): `/demo/call` India-only, consent row before dial, per-number/IP/global caps, kill switch `demo:kill`, overrides in `demo:config`. Details: `log.md`, `docs/issues/003-f02-demo-call-lockdown.md`.
- 004 (F09 log hygiene, 51b541c) and 011 (F07 turn release, e8998d4, `smart_backstop` 0.8 s) shipped and verified. Numbers: `docs/baselines/2026-10-23-011-exit.md`.
- **014 prompt v2 shipped as ae2aff2 (PR #40). Exit test 2026-10-24: PARTIAL PASS. Founder decision: not rolled back** (a revert would bring back end-after-booking, invented names and the AI denial). Full figures: `log.md`.
  - Passed: `TOOL end_call` 0 across Part A, all 10 keys `end_call_tool_invoked=false`; call 15 exactly 1 `end_call`, closing phrase once; 10 distinct `book_site_visit` sids; silent, "are you a bot", "which company" calls clean (no denial, no second greeting, no invented name); leak gates all 0; 0 of 109 turns stalled.
  - Missed: natural by ear 5 to 6 of 10 (bar 7); LLM first token p50 726 ms (gate 716); first-sentence wait p50 145 ms (gate 84); call 3 re-introduced itself mid-call ("hi my name is Aarya"), a zero-tolerance miss. No latency rerun (hypothesis in the inbox).
  - A transfer key showed `transfer_requested` blank although the tool fired: flag unreliability, 008's job.
- **015 L1 start-up shipped as 8b21625 (PR #42). Exit test 2026-10-24: PASS** (founder, 3 silent calls, T0 2026-10-24T16:01:32Z; reported, not run by an agent). Server `ws_connected` to `first_bot_audio_sent` 1,168 / 856 / 457 ms (gate 1,500). Stopwatch pickup to first word 4.3 / 4.2 / 3.89 s (6.5 s on a cold call before 015), so 3.1 to 3.4 s is outside our server (Exotel bridging, phone network; by subtraction, split unmeasured). `kb_source=cache`, `kb_ms=0` on all three; `models_ms` 111 / 102 / 98, under 150, so the model-preload follow-up is closed. Leak gates 0; the `last6` digits are per the founder, being confirmed. Figures: `log.md`.
- Decisions: AI disclosure `on_ask` for the demo; company spoken as "Next Layer"; payment plan said as a sentence (`decisions.md`).
- KB `UPDATE`s run 2026-10-23 by the founder in the Supabase SQL Editor, before the 014 merge (verified: whole config read back with `jsonb_pretty`, pricing untouched). `payment_plan.name` is now "Construction Linked Plan" with a `spoken` key and the four tranches unchanged; `objections.think_about_it` and `objections.price` replaced. The leftover-promise check (widened regex) returned 0 rows. The SQL was first tested on a scratch Postgres 16 (guards matched, a second run changed nothing, both rollbacks restored the originals). F05's KB half is therefore done.
- Payment plan said as a sentence (pass bar 4): no miss reported across the 10 Part A calls; not scored call by call, so this rests on the founder's notes rather than a per-call tally.
- The live site on `main` still has the F10 overclaims; F04, F05, F10, F11 are open. PRs #29–#31 closed unmerged, branches kept.
- Outreach to leads stays paused until the truthful tools, do-not-call and consent work (008, 006, 007) are live; demos that prospects call themselves are fine.
- Merge = deploy. Pushing `main` auto-deploys backend (deploy.yml, no path filter: a docs-only merge rebuilt the image and recreated the container, observed on PR #41) and frontend (Vercel). The first call after any merge or container recreate is cold (slow greeting): do not compare it with the rest of a batch.
- Schema: `commitments` + `consents` tables exist in prod (migration file not yet committed to repo).

## In flight
- Worktree `005-docs-specs-research` is open. Cap is 3 open worktrees.

## Next
1. Prompt v2.1 (inbox `2026-10-24-prompt-v2-1-over-corrected-into-terseness.md`): allow connectives and process phrases, keep content-free acknowledgements banned, fix the mid-call re-greeting and "Hi Aarya". Re-test latency in the same run.
2. KB rewrite as spoken sentences (digits in pricing, sizes, amenities; real competitor names): SQL only, founder runs it.
3. Backchannel versus barge-in (`bot.py:207-210`): an agreeing "haan" or fan noise cuts the bot dead.
4. TTS prosody: research task on ElevenLabs WebSocket versus HTTP; voice settings need the Flash A/B first (inbox).
5. Start-up levers left: keep-warm for the ElevenLabs voice (a cold voice costs about 640 ms, the largest lever we control); Exotel's 3.1 to 3.4 s (inbox); the dial tone before the greeting (cause unknown).
6. 012: caller name and form of address.
7. 008: truthful tools (write `commitments` rows, real tool results, reliable flags, notification).
8. STT A/B: amounts, and project names as Deepgram key terms.
9. Do-not-call.
10. Close 005; three-layer split plan (founder reviewing).

## Backlog (unordered)
`/start` unauthenticated; `WS_AUTH_MODE` code default to `enforce`; VPS reboot window; Docker log rotation; GitHub branch protection; `new-task.sh`/`finish-task.sh` worktree footgun; F02 test gaps and cooldown UX candidate; promote F02 guard into `architecture.md`; `deploy.yml` path filter (inbox); KB refresh debts (no overall deadline, no stale alert).

## Human-only pending
- Send Exotel email (DND / 140xx question) and the start-up questions (inbox `2026-10-24-ask-exotel-why-pickup-takes-3s.md`). Lawyer's answer on TRAI and DPDP (AI disclosure).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Check on the VPS what a `.env` edit does to redis state (`docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Agents never merge. Container logs are scrubbed since 004, but uvicorn's own lines are not: never paste logs unredacted.
- Exit-test greps for `TOOL …` and `prompt v2:` read `docker logs nxlyr_agent`, not `events.log` (latency lines only).
- Don't edit the VPS `.env` while calls are in flight (it recreates redis).
- Demo emergency stop, no deploy: `docker compose exec -T redis redis-cli SET demo:kill 1` (clear with `DEL demo:kill`).
- Latency files live in the container and are lost on every deploy: copy them off before deploying.
