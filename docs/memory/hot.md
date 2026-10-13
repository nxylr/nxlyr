# HOT — read every session (keep < 60 lines)

_Last updated: 2026-10-13 by setup kit. Update at the end of every task._

## State
- Live demo = `main` @ 80d4348 (verify: `git rev-parse --short origin/main`). Public, working, **unauthenticated** (audit F01/F02).
- The live site on `main` still contains the F10 overclaims (“Sending transcript”, “Updated CRM”, inbound-routing and DPDP claims); F04, F05, F10 and F11 are open. As of 2026-10-13, PRs #29–#31 are closed unmerged; their branches and diffs remain on GitHub, and the work can be reopened.
- Merge = deploy. Pushing `main` auto-deploys backend (deploy.yml) and frontend (Vercel).
- Schema: `commitments` + `consents` tables exist in prod (migration file not yet committed to repo).
- KB (`projects.config` for project 1c401a68-…) still promises WhatsApp/brochure sending (F05). Fix SQL prepared, not run.

## In flight
- Agent workflow setup (this kit).

## Next 3
1. Task 001 — F01: authenticate `/ws` (spec: docs/issues/001-f01-authenticate-ws.md). Needs one real call to prove Exotel call SID == `/ws` start-message `call_sid`.
2. Sandbox/test pipeline so new features can be tested without touching live `main`.
3. Transcript storage + tools persistence (after F01).

## Human-only pending
- Send Exotel email (DND / 140xx question).
- Commit migration file `20261007000000_phase0_commitments_consents.sql`.
- Enable GitHub branch protection on `main` if plan allows.
- Sales track starts 2026-10-14 (avoid festive peak ~Oct 11–20 and Diwali week ~Nov 8 for outreach timing).

## Do not forget
- Never `SELECT *` on `tenants`. Never paste logs unredacted. Agents never merge.
