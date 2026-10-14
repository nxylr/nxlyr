# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-14 by memory close-out (task 010, closing task 003). Update at the end of every task._

## State
- Live demo = `main` @ 870482a (verify: `git rev-parse --short origin/main`). Public, working.
- F01 shipped: PR #33 merged as 7cf8edf; `/ws` admits only calls bound by `/demo/call` (`ws_bind:<call_sid>`, 120s TTL, one-shot). Code default `WS_AUTH_MODE=log`; **per the founder, `WS_AUTH_MODE=enforce` is set in the VPS `.env`** (not verified by an agent; the switch lives only there).
- F02 shipped: PR #35 merged as 870482a (deploy.yml green, agent healthy). `/demo/call` accepts only `+91` mobiles (6–9, 10 digits), writes a `consents` row (granted / web_form / server-held wording v1) **before** dialling, and enforces per-number 3/24h, per-IP 10/24h, global 50/day, cooldowns 180s/30s. Redis kill switch `demo:kill`; runtime overrides in hash `demo:config`; commands in `docs/issues/003-f02-demo-call-lockdown.md` ("Operator commands"). Client IP = nginx `X-Real-IP` only. Fails closed when Redis or Supabase is unavailable (unit-tested; not proven live).
- F02 exit test passed on live production (founder, 2026-10-14, 870482a): see `log.md`. Spec step 7 was wrong (only the phone cooldown was lowered; the IP cooldown is checked first); the code was right.
- Not proven live: refunds as real events (Exotel failure, `consent_storage_failed`), Redis/Supabase down, IPv6 beyond the /64 note.
- Still open: `/start` is unauthenticated and refused under enforce (queued); no DND/TRAI scrubbing and no proof the submitter owns the number (consent = submitter's word); F23 `test_kb_loader` has 5 failures on `main`.
- The live site on `main` still contains the F10 overclaims (“Sending transcript”, “Updated CRM”, inbound-routing and DPDP claims); F04, F05, F10 and F11 are open. PRs #29–#31 are closed unmerged; their branches and diffs remain on GitHub, and the work can be reopened.
- Merge = deploy. Pushing `main` auto-deploys backend (deploy.yml) and frontend (Vercel).
- Schema: `commitments` + `consents` tables exist in prod (migration file not yet committed to repo). `/demo/call` now inserts into `consents` (append-only).
- KB (`projects.config` for project 1c401a68-…) still promises WhatsApp/brochure sending (F05). Fix SQL prepared, not run.

## In flight
- Task 010 — memory close-out for task 003 (this change). In review.
- Worktree `005-docs-specs-research` is open (not touched here). Cap is 3 open worktrees.

## Next
1. **Conversation harness, then prompt v2:** short turns, ask before pitching, honest AI disclosure, no brochure/WhatsApp promises, prompt moved out of `bot.py`.
2. **Real tools:** write `commitments` rows keyed by call SID, truthful tool results, Telegram notification. The founder reviews and runs migration `20261007000000_phase0_commitments_consents.sql` first (log says the tables were applied in prod 2026-10-07 and the file is uncommitted — reconcile before building).
3. **Latency:** preload the KB (F06), turn-release stall (F07).
4. **Hygiene batch (004):** `diagnose=False` at `bot.py:96` (pre-existing leaks at `server.py:255` Exotel key/token + phone and `server.py:570` phone); authenticate or remove `/start`; `WS_AUTH_MODE` code default to `enforce`; reboot window (VPS "System restart required", 50 pending updates; confirm compose restart policies for `agent`/`redis`, then reboot at a quiet hour and check health twice); fix the `new-task.sh`/`finish-task.sh` worktree footgun (path from `--show-toplevel`; use `--git-common-dir`); GitHub branch protection; F23 `test_kb_loader` errors.
5. **F02 follow-ups (with 006, call record):** three test gaps (IP-cooldown cleanup after a phone-cooldown refusal, missing `X-Real-IP` at the endpoint, TTL/cooldown values asserted for presence only). UX candidate: a request refused by the per-number cap still starts both cooldowns, so a user over the cap who retries within 3 minutes sees "cooldown" first.
6. Promote F02 into architecture.md (guard, kill switch, consent, X-Real-IP trust).

## Human-only pending
- Send Exotel email (DND / 140xx question).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Sales track starts 2026-10-14 (avoid festive peak ~Oct 11–20 and Diwali week ~Nov 8 for outreach timing).
- Check on the VPS what a `.env` edit does to redis state (see `docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Never paste logs unredacted (they can hold phone numbers and the Exotel key until task 004). Agents never merge.
- Don't edit the VPS `.env` while calls are in flight (it recreates redis).
- Demo emergency stop, no deploy: `docker compose exec -T redis redis-cli SET demo:kill 1` (clear with `DEL demo:kill`).
