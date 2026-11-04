# HOT — read every session (keep < 60 lines)

_Last updated: 2026-11-03 by memory close-out (task 024, closing 022 and 021). Update at the end of every task._

## State
- Live demo = `main`, last code change 7b0254a (PR #49, task 021, which merged 022 / PR #48, 00e93c6). Verify: `git rev-parse --short origin/main`. Merge = redeploy.
- **Technical work is paused for founder decisions; the 023 backend-architecture design is waiting in its worktree (uncommitted; do not touch it).**
- Shipped earlier: F01 `/ws` binding (PR #33; `enforce` in the VPS `.env` **per the founder, not verified by an agent**), F02 `/demo/call` lockdown (PR #35, kill switch `demo:kill`), 004 log hygiene, 011 turn release, 014 prompt v2, 015 start-up, 018 conversation v2.1 (67e3466), 019 voice config (d9a23f3), 008 truthful tools (2eed24e). Figures and exit results: `log.md`.
- **The 022 and 021 results below are per the founder, not verified by an agent.**
- **022 smart barge-in (00e93c6): PASS** (real calls 2 and 3 Nov; legacy unchanged). Coughs (`no_words`) and "haan" / "uh-huh" (agreement) were ignored and the bot kept talking. "Wait" interrupted in 217 ms, real sentences in 275 to 564 ms, `clear` sent within 6 to 9 ms of the decision. Watch items: speakerphone with a fan untested; "theek hai" still interrupts in English mode (en-IN hears it as English words).
- **021 Hinglish (7b0254a): PASS with watch items.** Calls ran on `language=multi` on `api.eu.deepgram.com`, no STT fallback, no "Connection lost", no failed writes. Watch items: one Hinglish interruption took 2,174 ms from speech start to fire; Hindi booking not yet exercised (`product.md` stays unchanged until a Hindi booking is tested on a real call).
- **Voice (per the founder):** v4 ignored the accent tag and `language_code` for the current voice (four test files sounded identical). A more Indian-sounding voice is parked.
- **Live Redis settings (per the founder, not verified):** `convo:config` prompt_version=v21 stt_keyterms=on stt_region=eu greeting_tags=on bargein_mode=smart language_mode=hinglish. `voice:config` model=eleven_v4_turbo voice=9lx2GDtpvyyNBM7O9Mmx. Code defaults are unchanged (v2, no key terms, global host, plain greeting, legacy barge-in, English); `DEL convo:config` / `DEL voice:config` revert a call to them. See `architecture.md`.
- Founder decision 2026-10-27: the beachhead is Gurugram residential developers (`decisions.md`). Also in force: AI disclosure `on_ask`; company spoken "Next Layer"; payment plan said as a sentence.
- KB `UPDATE`s run 2026-10-23 by the founder (`payment_plan.spoken`, two objections). The rest of the KB still holds digits (inbox).
- The live site on `main` still has the F10 overclaims; F05, F10, F11 are open. PRs #29–#31 closed unmerged, branches kept.
- Outreach to leads stays paused until do-not-call and consent work (006, 007) is live. Demos that prospects call themselves are fine.
- Merge = deploy. `deploy.yml` has no path filter: a docs-only merge rebuilds the image and recreates the container. The first call after any merge is cold: do not compare it with the rest of a batch.
- Production `LOG_LEVEL` is DEBUG (unset in the VPS `.env`) until the founder sets INFO; unset, never empty (empty crashes boot).
- Schema: `commitments`, `consents` and `call_commitments` exist in prod. `call_commitments` is recorded in `supabase/migrations/20261025000000_create_call_commitments.sql`; the migration file for the other two is not yet in the repo.

## In flight
- Task 024 (this memory close-out). 023 backend architecture: paused, design in `../nxlyr-worktrees/023-backend-architecture`. This close-out took number 024, so 023's planned task split (024 to 028) will be renumbered from 025 when the backend work resumes. Cap is 3 worktrees; two are open.

## Next
Gurugram plan: (1) truthful landing page (remove the F10 overclaims; claims only from `product.md`); (2) demo funnel alerts on Telegram; (3) demo hygiene: `deploy.yml` path filter, a test allowlist for the founder's number, `LOG_LEVEL=INFO`; (4) prospect demo kit; (5) call transcripts and post-call summary; (6) cost per call.
Parked from 021 and 022 (not started):
- 029 per-sentence TTS requests (WebSocket streaming); see the TTS prosody inbox note.
- English prompt rule for "set for / fixed for / scheduled for" (inbox `2026-11-02-english-booking-claim-needs-prompt-rule.md`); needs its own A/B test.
- More Hindi backchannel words in `AGREEMENT_PHRASES` (en-IN hears "theek hai" as English).
- Hinglish interruption latency (2,174 ms once).
- An Indian-accent voice.
- The redundant `websockets.legacy` import in `agent/stt_keyterms.py`.
- The English-mode STT handler logs Deepgram exceptions verbatim (the Hinglish handler logs only the type name).

## Backlog (unordered)
KB rewrite as spoken sentences (SQL, founder runs); Exotel's 3.1 to 3.4 s and the dial tone before the greeting; 012 caller name; do-not-call (006, 007); close 005 and the three-layer split plan; second LLM call on successful tool turns (inbox); `/start` unauthenticated; `WS_AUTH_MODE` code default to `enforce`; VPS reboot window; Docker log rotation; GitHub branch protection; `new-task.sh`/`finish-task.sh` worktree footgun; F02 test gaps and cooldown UX; KB refresh debts.

## Human-only pending
- Set `LOG_LEVEL=INFO` on the VPS. Send the Exotel email (DND / 140xx and start-up questions); lawyer's answer on TRAI and DPDP (AI disclosure).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`. Enable branch protection if the plan allows.
- Check what a `.env` edit does to redis state (inbox `2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Agents never merge. Container logs are scrubbed since 004, but uvicorn's own lines are not: never paste logs unredacted.
- Exit-test greps for `TOOL …`, `prompt v2:`, `barge-in:` and `stt fallback:` read `docker logs nxlyr_agent`, not `events.log` (latency lines only).
- Don't edit the VPS `.env` while calls are in flight (it recreates redis). Switches in Redis (`convo:config`, `voice:config`) need no deploy.
- Demo emergency stop, no deploy: `docker compose exec -T redis redis-cli SET demo:kill 1` (clear with `DEL demo:kill`).
- Latency files live in the container and are lost on every deploy: copy them off before deploying.
