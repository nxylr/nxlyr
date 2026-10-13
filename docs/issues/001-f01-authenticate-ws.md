---
name: Task spec
title: "001: Authenticate /ws (audit F01)"
labels: task, audit
---

## Goal
Only calls that our own `/demo/call` placed can open a paid agent session on `/ws`. Anyone else is rejected before any expensive setup (STT/LLM/TTS connections, KB fetch).

## Context
Audit F01: `/ws` is unauthenticated; a caller-supplied call SID selects the Redis namespace. Anyone can run the paid agent. Read `docs/memory/architecture.md`.

## Files in scope
- `agent/server.py` (`/demo/call`, `/ws`)
- `agent/ws_auth.py`
- `agent/test_ws_auth.py`
- `agent/.dockerignore`
- `scripts/ws_probe.py` (anonymous probe tool; takes no secrets)
- `docs/memory/inbox/` notes

## Out of scope
- F02 (consent/DND/invite-code), F03 (persisting bookings), F06, F07, F14, nginx, deploy.yml, schema changes, frontend.
- Any `calls` / `leads` inserts.
- Quota logic.
- Source-IP allow-listing (source IP was not captured in the evidence call, so there is no basis for one).

## Design (approved by human)
One-shot Redis binding, enforced by `WS_AUTH_MODE`:
1. `/demo/call` dials Exotel; on a real Call SID in the response it stores `{"issued_at": <timestamp>}` under `ws_bind:<sid>` with 120s TTL. The binding holds no phone number or IDs. `/start` dials without a binding and is refused in `enforce` mode.
2. `/ws` accepts, then reads the start message with a **timeout and a size limit**. It consumes the binding atomically with `GETDEL`, polling up to ~3s because the websocket can arrive before the binding is written. No binding → close the socket with a policy-violation code **before** building the pipeline.
3. **Fail closed:** if Redis is unavailable, treat it as no binding (reject in `enforce` mode).
4. **Admission limit:** an in-process counter, incremented on admit and decremented in `finally`. `MAX_CONCURRENT_WS` (default 10); reject beyond it.
5. **`WS_AUTH_MODE=log|enforce`, default `log`.** In `log` mode never reject: only log `ws_auth would_reject` (with reason) and continue; log `ws_auth bound ok` on a valid binding. In `enforce` mode reject as above.
6. **Logging:** logs never contain phone numbers or secrets (no prompts, no Redis URL, no start-message payload beyond the SID).

## Step 1 evidence (done)
- Call SID from the dial and `call_sid` in the `/ws` start message were identical (`f19adf90…1aad`). The assumption holds, so no `CustomField` fallback is needed.
- Dial to answer took about 12 seconds (the 120s TTL and ~3s poll are comfortably sized).
- Source IP of the websocket: **not captured**.

## Open questions
- Handshake token (e.g. passed via Exotel `CustomField` or the `wss://` URL and checked at accept time) as defence in depth against a leaked or guessed SID. Not part of this task; decide after F01 ships.

## Acceptance criteria
- [ ] Unit tests: no binding → rejected; valid binding → accepted once; replay of the same SID → rejected; over limit → rejected; Redis unavailable → rejected (fail closed); oversized or late start message → rejected.
- [ ] `log` mode never rejects and logs `ws_auth would_reject`; `enforce` mode rejects.
- [ ] Rejection happens before pipeline construction (test asserts no STT/LLM/TTS objects created).
- [ ] Counter is decremented on every exit path, including exceptions.
- [ ] No behaviour change for a legitimate demo call.
- [ ] `python -c "import server"` passes; existing tests pass.
- [ ] No phone numbers or secrets added to logs or to the binding.

## Steps
1. ✅ 👀🧑 **Evidence call.** Done 2026-10-13: Call SID matched; see "Step 1 evidence".
2. 🤖 Claude (lead) reviews evidence, confirms or revises the Design; human approves.
3. 🤖 Codex builds in worktree `task/001-f01-authenticate-ws`.
4. 👀 Human reads the diff (before commit).
5. 🤖 Different model reviews (Claude Code review of the diff).
6. 🤖 PR with 10-section report.
7. 🧑 Exit test (below). Human merges.

## Exit test (real)
1. 🧑 Deploy in `WS_AUTH_MODE=log` (default). Check container health twice, a few seconds apart.
2. 🧑 Place a real demo call → it connects, the agent speaks, and the logs show `ws_auth bound ok`.
3. 🧑 Run `scripts/ws_probe.py` against `wss://api.infrasmith.dev/ws` → the logs show `ws_auth would_reject`.
4. 🧑 Set `WS_AUTH_MODE=enforce` in `.env` directly on the VPS (never via an agent) and redeploy (`git pull` + `docker compose up -d --build`). Check container health twice.
5. 🧑 Place a real demo call → it still connects.
6. 🧑 Run `scripts/ws_probe.py` → the connection is refused.
7. 🧑 Replay a used SID → refused.

## Builder / Reviewer
- Builder: codex
- Reviewer (must differ): Claude Code review of the diff. Do not use `/codex:review`, because that would be the builder's own model.

## Rollback
Set `WS_AUTH_MODE=log` on the VPS and redeploy, or revert the merge commit on `main` (merge = deploy, so the revert redeploys). Check health twice.
