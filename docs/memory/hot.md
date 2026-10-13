# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-13 by memory close-out (task 002). Update at the end of every task._

## State
- Live demo = `main` @ 7cf8edf (verify: `git rev-parse --short origin/main`). Public, working.
- F01 shipped: PR #33 merged as 7cf8edf; `/ws` admits only calls bound by `/demo/call` (`ws_bind:<call_sid>`, 120s TTL, one-shot). Code default `WS_AUTH_MODE=log`; **per the founder, `WS_AUTH_MODE=enforce` is set in the VPS `.env`** (not verified by an agent; the switch lives only there).
- 2026-10-13: the Exotel Call SID matched the `/ws` start-message `call_sid` on one real call.
- Still open: `/start` is unauthenticated and refused under enforce (queued); F02 `/demo/call` consent/DND untouched; F23 `test_kb_loader` has 5 failures on `main`.
- The live site on `main` still contains the F10 overclaims (“Sending transcript”, “Updated CRM”, inbound-routing and DPDP claims); F04, F05, F10 and F11 are open. PRs #29–#31 are closed unmerged; their branches and diffs remain on GitHub, and the work can be reopened.
- Merge = deploy. Pushing `main` auto-deploys backend (deploy.yml) and frontend (Vercel).
- Schema: `commitments` + `consents` tables exist in prod (migration file not yet committed to repo).
- KB (`projects.config` for project 1c401a68-…) still promises WhatsApp/brochure sending (F05). Fix SQL prepared, not run.

## In flight
- Task 002 — memory close-out for task 001 (docs/memory, AGENTS.md Commands, `new-task.sh --no-track`). In review.

## Next
1. Authenticate or remove `/start` (unauthenticated; places a call with no binding, so `/ws` refuses it under enforce).
2. Sandbox/test pipeline so new features can be tested without touching live `main`.
3. Transcript storage + tools persistence.
4. After a day of clean enforce running: flip the `WS_AUTH_MODE` code default to `enforce`, or add a startup warning when running in log mode. The switch currently lives only in the VPS `.env`, so a deploy without it silently runs in log mode.
5. Planned maintenance window: VPS shows "System restart required" and 50 pending updates. Confirm compose restart policies for `agent` and `redis` (repo copy: `unless-stopped` / `always`; verify on the VPS), then reboot at a quiet hour and check container health twice.
6. Fix the 5 pre-existing `test_kb_loader` failures on `main` (F23).

## Human-only pending
- Send Exotel email (DND / 140xx question).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Sales track starts 2026-10-14 (avoid festive peak ~Oct 11–20 and Diwali week ~Nov 8 for outreach timing).
- Check on the VPS what a `.env` edit does to redis state (see `docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Never paste logs unredacted. Agents never merge.
- Don't edit the VPS `.env` while calls are in flight (it recreates redis).
