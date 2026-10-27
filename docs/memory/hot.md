# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-27 by memory close-out (task 020, closing 018, 019, 008). Update at the end of every task._

## State
- Live demo = `main`, last code change 2eed24e (PR #46, task 008). Verify: `git rev-parse --short origin/main`. Merges since 015: 018 67e3466 (25 Oct), 019 d9a23f3 (26 Oct), 008 2eed24e (27 Oct). Merge = redeploy.
- Earlier, shipped: F01 `/ws` binding (PR #33; `enforce` in the VPS `.env` **per the founder, not verified by an agent**), F02 `/demo/call` lockdown (PR #35, kill switch `demo:kill`), 004 log hygiene, 011 turn release, 014 prompt v2 (PARTIAL PASS, not rolled back), 015 start-up (PASS). Figures: `log.md`.
- **The three exit results below are per the founder, not verified by an agent.**
- **018 conversation v2.1 (67e3466): PASS.** EU Deepgram endpoint: speech recognition about 275 ms per turn against about 360 (2 EU calls, 14 global, ranges did not overlap). Key terms: project-name near-misses 0 of 6 calls against 6 of 10. First-sentence wait p50 under 100 ms on every v2.1 block. Numerals redundant (Deepgram formatting already gives digits); Part B skipped. Harness: `claimed_without_tool` 0, `ending_in_question` 59 of 115.
- **019 voice config (d9a23f3): PASS.** Calls without an override unchanged; keep-warm running. v4 probe: v4 accepts `previous_text`, stability, similarity, style, speed and speaker boost, and rejects `optimize_streaming_latency` with 400 `unsupported_model` (019 drops that on v4). A 200 means accepted or ignored, not used; ElevenLabs says style and speed are not available on v4, so the code's drop of them is correct (inbox `2026-10-27-v4-probe-200-is-accepted-or-ignored.md`).
- **008 truthful tools (2eed24e): PASS.** 2 live calls: booking, correction (one live row, one superseded, both alerted), refusals, callback request, goodbye verified; 0 failed writes; leak counts 0. A booking or callback is reported only after a `call_commitments` row is stored and a Telegram alert is delivered.
- **Live Redis settings (per the founder, not verified):** `convo:config` prompt_version=v21 stt_keyterms=on stt_region=eu greeting_tags=on. `voice:config` model=eleven_v4_turbo (voice from env, GQrVSQduiFCVTMHGavV5); `convo:config` greeting_tags=on (voice chosen after live calls on 27 Oct). Code defaults are unchanged (v2, no key terms, global host, plain greeting, current voice); `DEL convo:config` / `DEL voice:config` revert a call to them. See `architecture.md`.
- Founder decision 2026-10-27: the beachhead is Gurugram residential developers (`decisions.md`).
- Decisions in force: AI disclosure `on_ask`; company spoken "Next Layer"; payment plan said as a sentence.
- KB `UPDATE`s run 2026-10-23 by the founder (`payment_plan.spoken`, two objections). The rest of the KB still holds digits (inbox).
- The live site on `main` still has the F10 overclaims; F05, F10, F11 are open (F04 closed by 008). PRs #29–#31 closed unmerged, branches kept.
- Outreach to leads stays paused until do-not-call and consent work (006, 007) is live; the truthful tools (008) are now live. Demos that prospects call themselves are fine.
- Merge = deploy. `deploy.yml` has no path filter: a docs-only merge rebuilt the image and recreated the container (PR #41). The first call after any merge is cold: do not compare it with the rest of a batch.
- Production `LOG_LEVEL` is DEBUG (unset in the VPS `.env`) until the founder sets INFO; unset, never empty (empty crashes boot).
- Schema: `commitments`, `consents` and `call_commitments` exist in prod. `call_commitments` is recorded in `supabase/migrations/20261025000000_create_call_commitments.sql`; the migration file for the other two is not yet in the repo.

## In flight
- Task 020 (this memory close-out). No other worktree is open. Cap is 3.

## Next (Gurugram plan)
1. Truthful landing page (remove the F10 overclaims; claims only from `product.md`).
2. Demo funnel alerts on Telegram (who filled the form, who answered, who booked).
3. Demo hygiene: `deploy.yml` path filter (inbox), a test allowlist for the founder's number, `LOG_LEVEL=INFO`.
4. Prospect demo kit: one project sheet per prospect, reached by a link.
5. Call transcripts and a post-call summary.
6. Cost per call.

## Backlog (unordered)
KB rewrite as spoken sentences (SQL, founder runs); backchannel versus barge-in (`bot.py`); TTS prosody research (inbox); Exotel's 3.1 to 3.4 s and the dial tone before the greeting; 012 caller name; do-not-call (006, 007); close 005 and the three-layer split plan; second LLM call on successful tool turns (inbox, option C); `/start` unauthenticated; `WS_AUTH_MODE` code default to `enforce`; VPS reboot window; Docker log rotation; GitHub branch protection; `new-task.sh`/`finish-task.sh` worktree footgun; F02 test gaps and cooldown UX; KB refresh debts.

## Human-only pending
- Set `LOG_LEVEL=INFO` on the VPS.
- Send the Exotel email (DND / 140xx and the start-up questions); lawyer's answer on TRAI and DPDP (AI disclosure).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`. Enable branch protection if the plan allows.
- Check what a `.env` edit does to redis state (inbox `2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Agents never merge. Container logs are scrubbed since 004, but uvicorn's own lines are not: never paste logs unredacted.
- Exit-test greps for `TOOL …` and `prompt v2:` read `docker logs nxlyr_agent`, not `events.log` (latency lines only).
- Don't edit the VPS `.env` while calls are in flight (it recreates redis). Switches in Redis (`convo:config`, `voice:config`) need no deploy.
- Demo emergency stop, no deploy: `docker compose exec -T redis redis-cli SET demo:kill 1` (clear with `DEL demo:kill`).
- Latency files live in the container and are lost on every deploy: copy them off before deploying.
