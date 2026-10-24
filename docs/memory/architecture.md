# Architecture (verified facts only — mark anything else `UNVERIFIED:`)

## Call flow
1. Visitor submits demo form (dashboard, Vercel) → `POST /demo/call` on `api.infrasmith.dev` (nginx → agent container).
2. Server dials via Exotel Connect API (Basic auth). On a real Call SID it writes `ws_bind:<call_sid>` to Redis (`{"issued_at": <ts>}`, 120s TTL). Exotel then opens `wss://api.infrasmith.dev/ws`.
3. `/ws` (`agent/server.py`, `agent/ws_auth.py`): accept → read the handshake (`connected`/`start`, 5s timeout, 16 KiB limit) → `GETDEL ws_bind:<call_sid>` (polled up to ~3s, 1s Redis timeouts) → in-process admission counter (`MAX_CONCURRENT_WS`, default 10) → `run_bot` with the consumed frames replayed. The Exotel Call SID equals the start-message `call_sid` (verified on one real call, 2026-10-13).
   - `WS_AUTH_MODE=log|enforce`, code default `log`. Enforce closes with 1008 before any pipeline object is built and fails closed if Redis is unavailable. Log mode never rejects: it logs `ws_auth would_reject reason=…` and continues; an unbound call is held ~3s by the poll. The mode is read per connection from the environment.
   - `scripts/ws_probe.py` is an anonymous probe (no secrets) that prints the close code.
4. `agent/bot.py` runs the Pipecat pipeline: Silero VAD with VAD and transcription turn-start strategies → Deepgram STT → GPT-4o → ElevenLabs (HTTP TTS).
   - Turn release (task 011, PR #37): Smart Turn v3 decides first, with a speech-timeout backstop; Silero VAD stop is 0.2 s (pipecat default). `NXLYR_TURN_MODE` (`smart_backstop` default, or `speech_timeout`) and `NXLYR_TURN_BACKSTOP_SECS` (0.3 to 2.0, default 0.8) are validated at import, so a bad value stops the container at start. The live mode line is `turn release configured: mode=… backstop_secs=…`.
   - Logging (task 004, PR #38): `agent/log_scrub.py` installs one loguru handler with `diagnose` off, drops `pipecat.services.openai.base_llm` DEBUG lines, masks phones to the last 4 digits, and removes secret env values and token shapes. `LOG_LEVEL` still defaults to DEBUG. uvicorn's own lines are not scrubbed.
   - Measurement: `section6_real_call_events.log` is the primary latency source; both latency files live in the container and are lost on every deploy, so copy them off before deploying.
5. Tools in `agent/tools.py` (`book_site_visit`, `transfer_to_human`, `end_call`) write flags to a Redis session hash (4h TTL). Nothing downstream reads them yet.
6. `agent/kb_loader.py` loads `projects.config` from Supabase (300s manual TTL cache; blocking `requests.get` — audit F06).

## Infra
- Hetzner VPS, `/opt/nxlyr`, docker compose, nginx at `api.infrasmith.dev`. Redis in a container.
- Repo copy of `docker-compose.yml`: agent and redis publish on `127.0.0.1` only; both read `env_file: /mnt/secrets/.env`. A local `docker-compose.override.yml` (gitignored) repoints env_file for laptops.
- Repo copy of `infra/nginx/api.infrasmith.dev.conf` (not necessarily what is live): proxies `/ws` (prefix), `/demo/call` (prefix, CORS for `https://nxlyr.vercel.app`) and `= /contact` to `127.0.0.1:7860`. Everything else, including `/start` and `/health`, falls to static `location /` → 404. So `/health` returns an nginx 404 externally (observed by the human too); the container healthcheck hits it on loopback. The real gate is a real call.
- Frontend: Next.js in `dashboard/`, Vercel production follows `main`.
- CI/CD: `.github/workflows/deploy.yml` — on push to `main`: SSH → `cd /opt/nxlyr && git pull origin main && docker compose up -d --build`. No path filter: every push to `main`, including a docs-only merge, runs the SSH step (checked in the workflow file on 2026-10-24), so every merge is a redeploy attempt. Whether `docker compose up -d --build` recreates the container for a docs-only change depends on whether the image changes (UNVERIFIED). No concurrency control. Build runs an `import server` smoke. No workflow runs the unit tests; `lint.yml` checks `api/` (empty) and always passes.
- Local runs: `agent/venv` exists only in the main checkout (gitignored); see AGENTS.md "Commands".

## Supabase tables (live)
tenants (has `api_key` — never SELECT *), projects (`config` jsonb = KB), leads (unique project_id + phone_normalized), calls (`exotel_call_id` unique, lead_id/tenant_id NOT NULL), call_events (payload jsonb), transcripts (one row per call: content, turns jsonb, word_count), qualifications (unique per lead), analytics_daily, voice_clones, contact_submissions, commitments, consents (RLS on, no policies; service role bypasses).

## Known gaps (from independent audit, F-numbers)
F02 shipped (PR #35; DND screening still open) · F03 bookings only in Redis · F04 tool errors swallowed · F05 prompt/KB promise brochure/WhatsApp · F06 blocking KB fetch · F07 shipped (PR #37) · F09 shipped (PR #38) · F12 missing timeouts · F13 non-atomic INCR/EXPIRE · F14 Exotel 200 without SID treated as success · F23 `agent.test_kb_loader` has 5 failures on `main`.
- `/start` is unauthenticated and unrate-limited and places a call with no binding (so `/ws` refuses it under enforce). Not proxied by the repo nginx copy.
- F01 (`/ws` unauthenticated) was fixed by PR #33 (7cf8edf). Enforcement depends on `WS_AUTH_MODE=enforce` in the VPS `.env` (reported by the founder; not verified by an agent).

## Unproven assumptions
- UNVERIFIED: Exotel DND screening applies to our ExoPhone (regular 011 number) vs. required 140xx for promotional calls — question sent/pending to Exotel.
- Likely, not proven: redis data survives a `.env`-triggered container recreate (`nxlyr_redis_data` volume present; `DBSIZE` was 7 right after one). See `inbox/2026-10-13-env-edit-recreates-redis.md`.
