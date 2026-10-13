# Architecture (verified facts only — mark anything else `UNVERIFIED:`)

## Call flow
1. Visitor submits demo form (dashboard, Vercel) → `POST /demo/call` on `api.infrasmith.dev` (nginx → agent container).
2. Server dials via Exotel Connect API (Basic auth). Exotel then opens `wss://api.infrasmith.dev/ws`.
3. `/ws` runs the Pipecat pipeline in `agent/bot.py`: Silero VAD with VAD and transcription turn-start strategies → Deepgram STT → GPT-4o → ElevenLabs (HTTP TTS).
4. Tools in `agent/tools.py` (`book_site_visit`, `transfer_to_human`, `end_call`) write flags to a Redis session hash (4h TTL). Nothing downstream reads them yet.
5. `agent/kb_loader.py` loads `projects.config` from Supabase (300s manual TTL cache; blocking `requests.get` — audit F06).

## Infra
- Hetzner VPS, `/opt/nxlyr`, docker compose, nginx at `api.infrasmith.dev`. Redis in a container.
- Frontend: Next.js in `dashboard/`, Vercel production follows `main`.
- CI/CD: `.github/workflows/deploy.yml` — on push to `main`: SSH → `cd /opt/nxlyr && git pull origin main && docker compose up -d --build`. No concurrency control. Build runs an `import server` smoke.

## Supabase tables (live)
tenants (has `api_key` — never SELECT *), projects (`config` jsonb = KB), leads (unique project_id + phone_normalized), calls (`exotel_call_id` unique, lead_id/tenant_id NOT NULL), call_events (payload jsonb), transcripts (one row per call: content, turns jsonb, word_count), qualifications (unique per lead), analytics_daily, voice_clones, contact_submissions, commitments, consents (RLS on, no policies; service role bypasses).

## Known gaps (from independent audit, F-numbers)
F01 `/ws` unauthenticated · F02 `/demo/call` dials any E.164, no consent/DND check · F03 bookings only in Redis · F04 tool errors swallowed · F05 prompt/KB promise brochure/WhatsApp · F06 blocking KB fetch · F07 ~3s turn-release stall · F09 prompts/Redis URL logged · F12 missing timeouts · F13 non-atomic INCR/EXPIRE · F14 Exotel 200 without SID treated as success.

## Unproven assumptions
- UNVERIFIED: Exotel Connect API call SID equals the `call_sid` in the `/ws` start message. Needs one real call to confirm (blocks F01 design).
- UNVERIFIED: Exotel DND screening applies to our ExoPhone (regular 011 number) vs. required 140xx for promotional calls — question sent/pending to Exotel.
