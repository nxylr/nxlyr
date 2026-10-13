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
- `agent/` new helper module for the binding (if needed)
- new tests under `agent/`
- `docs/memory/inbox/` notes

## Out of scope
- F02 (consent/DND/invite-code), F03 (persisting bookings), F06, F07, nginx, deploy.yml, schema changes, frontend.

## Design (approved by human before build)
One-shot Redis binding:
1. `/demo/call` dials Exotel; on a real Call SID in the response it stores `{call_id, lead_id, tenant_id, project_id}` (whichever exist today) in Redis under `ws_bind:<sid>` with 120s TTL.
2. `/ws` reads the start message, then atomically consumes the binding (`GETDEL`, or Lua if Redis < 6.2), polling up to ~3s because the websocket can arrive before the binding is written. No binding → close the socket with a policy-violation code **before** building the pipeline.
3. Admission limit `MAX_CONCURRENT_WS` (default 10): reject beyond it.
4. Optional `EXOTEL_WS_ALLOWED_IPS` allow-list (env, off by default; the human sets it on the VPS).
5. Log rejections without logging secrets.

**Unproven assumption:** the Connect API Call SID equals `call_sid` in the `/ws` start message. Step 1 below must prove it. If it does not, fallback = pass a token via Exotel `CustomField` and read it from the start message; stop and report before implementing the fallback.

## Acceptance criteria
- [ ] Unit tests: no binding → rejected; valid binding → accepted once; replay of the same SID → rejected; over limit → rejected.
- [ ] Rejection happens before pipeline construction (test asserts no STT/LLM/TTS objects created).
- [ ] No behaviour change for a legitimate demo call.
- [ ] `python -c "import server"` passes; existing tests pass.
- [ ] No secrets or full prompts added to logs.

## Steps
1. 👀🧑 **Evidence call.** Human places one real demo call on the current live system. Capture (redacted): Call SID returned by `/demo/call`/Exotel response, `call_sid` from the `/ws` start message in container logs, and the source IP of the websocket in nginx/container logs. Check logs for secrets before sharing with any agent.
2. 🤖 Claude (lead) reviews evidence, confirms or revises the Design; human approves.
3. 🤖 Codex builds in worktree `task/001-f01-authenticate-ws`.
4. 👀 Human reads the diff (before commit).
5. 🤖 Different model reviews (`/codex:adversarial-review` from Claude Code).
6. 🤖 PR with 10-section report.
7. 🧑 Exit test (below). Human merges.

## Exit test (real)
- 🧑 After merge+deploy, check container health twice a few seconds apart.
- 🧑 Place a real demo call → it connects and the agent speaks; a `calls` row exists for that call.
- 🧑 From your laptop, open a websocket to `wss://api.infrasmith.dev/ws` with a fabricated start message → connection is closed immediately and no paid API usage appears.
- 🧑 Place a second demo call → still works (binding not stuck).

## Builder / Reviewer
- Builder: codex
- Reviewer (must differ): claude (or codex-plugin-cc adversarial review run from Claude Code)

## Rollback
Revert the merge commit on `main` (merge = deploy, so the revert redeploys). Check health twice.
