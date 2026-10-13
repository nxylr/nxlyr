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
Plan for 2026-10-14, in order:
1. **F02 — lock down `/demo/call`:** Indian mobiles only, consent stored in `consents`, per-number and per-IP caps, kill switch.
2. **Conversation harness, then prompt v2:** short turns, ask before pitching, honest AI disclosure, no brochure/WhatsApp promises, prompt moved out of `bot.py`.
3. **Real tools:** write `commitments` rows keyed by call SID, truthful tool results, Telegram notification. The founder reviews and runs migration `20261007000000_phase0_commitments_consents.sql` first (log says the tables were applied in prod 2026-10-07 and the file is uncommitted — reconcile before building).
4. **Latency:** preload the KB (F06), turn-release stall (F07).
5. **Hygiene batch:** authenticate or remove `/start`; log hygiene (`diagnose=False`); `WS_AUTH_MODE` code default to `enforce`; reboot window (VPS "System restart required", 50 pending updates; confirm compose restart policies for `agent`/`redis`, then reboot at a quiet hour and check health twice); fix the `new-task.sh`/`finish-task.sh` worktree footgun (they build the worktree path from `--show-toplevel`; use `--git-common-dir`); GitHub branch protection; F23 `test_kb_loader` errors.

## Human-only pending
- Send Exotel email (DND / 140xx question).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Sales track starts 2026-10-14 (avoid festive peak ~Oct 11–20 and Diwali week ~Nov 8 for outreach timing).
- Check on the VPS what a `.env` edit does to redis state (see `docs/memory/inbox/2026-10-13-env-edit-recreates-redis.md`).

## Do not forget
- Never `SELECT *` on `tenants`. Never paste logs unredacted. Agents never merge.
- Don't edit the VPS `.env` while calls are in flight (it recreates redis).
