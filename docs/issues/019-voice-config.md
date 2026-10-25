# 019 — Voice config: a voice the founder can tune between calls, and a voice that is never cold

**Status: APPROVED r2 (founder approved 2026-10-25). No code written yet.**
Worktree `../nxlyr-worktrees/019-voice-config`, branch `task/019-voice-config`, from `origin/main` at `e3dca41` (015 merged as `8b21625`).
Covers: voice quality (founder's top priority with the prompt); ElevenLabs voice settings, all unset today; the cold voice (about 640 ms on the first call after idle); the Flash v2.5 against `eleven_v4_turbo` comparison.

**What changed from r1 (founder's answers and changes of 25 Oct):**
- Step 0 was run by the founder: production is `eleven_flash_v2_5` with voice `GQrVSQduiFCVTMHGavV5`. The code default is untouched.
- `eleven_v4_turbo` is now the main candidate in exit test B; Flash with the founder's settings is the comparison (B1).
- The settings sent depend on the model: for any `eleven_v4*` model only `stability` and `similarity_boost` go out; the rest are dropped and the log line says which (`dropped=`) (B2).
- `voice_cfg` is the fixed name of the resolved config in `run_bot`, the meeting point with 018 (B3).
- A small filter strips `[bracketed]` tags from spoken text when the model is not v4. Pipecat has the hook, so it is built (B4).
- `previous_text` for v4 checked in the installed code (B5), and exit test B gets a pre-flight probe because of it.
- Exit test B reworked: v4 first, tone and closing-line scores, cost line in Not verified (B6). Pronunciation dictionaries stay out (B7).
- All eight r1 questions answered; they are recorded at the end.

## Goal

1. The founder changes the voice between two test calls with one `redis-cli` command: no deploy, no `.env` edit, no restart. Settable: provider, model, voice, `stability`, `similarity_boost`, `style`, `use_speaker_boost`, `speed`, `optimize_streaming_latency`.
2. Each value resolves per field as: Redis override, else environment, else today's behaviour. An invalid value falls back with a WARNING and never breaks a call.
3. On merge with no override set, nothing a caller hears changes.
4. One log line per call states the provider, model, settings sent and settings dropped. No key, no secret.
5. A keep-warm request to the configured voice and model every 240 s while the server is up, so the first call after a quiet spell does not pay for a cold voice (greeting TTS 160 ms warm, 537 ms after 30 min, 744 to 802 ms after 2 h; 1,582 ms after 13 h).
6. Make `eleven_v4_turbo` testable on real calls safely: the founder heard it sound best in the web app, with the production voice and audio tags. A model that rejects a setting must not be able to silence a call.

## Non-goals

- Audio tags in the prompt, and the tagged greeting. That is 018, which uses `voice_cfg.model` from this task (see Overlap). This task only guarantees that tags are not spoken on a non-v4 model (the filter below).
- Moving to `ElevenLabsTTSService` (WebSocket). Agreed not in this task; proposed as task 021 (see the end).
- Pronunciation dictionaries (B7). If "crore" or "Aetheria" still sounds wrong on v4 in exit test B, that becomes a follow-up.
- No prompt change: `git diff origin/main -- agent/prompt.py` is empty.
- No second TTS provider is built. `provider` is a validated field whose only accepted value is `elevenlabs`; a second provider is likely later.
- No `apply_text_normalization`, no request stitching.
- No change to turn release, VAD, STT or the LLM. `bot.py` edits stay inside the text-to-speech block plus one import line; nothing near the user aggregator (020) or the greeting and messages (018).
- No schema change, no Supabase access, no new dependency (`aiohttp`, `redis` and Pipecat are already in `requirements.txt`).
- No `.env` edit by an agent (CONSTRAINTS rule 5). `.env.template` gets the new variable names, blank.

## What I read (and what I did not)

All line ranges are in this worktree at `e3dca41`, and in the installed Pipecat 1.5.0 (`agent/venv` of the main checkout). Anything not read or not run is marked UNVERIFIED.

| Where | Lines | What it showed |
| --- | --- | --- |
| `agent/bot.py` TTS block in `run_bot` | 466-482 | A per-call `aiohttp.ClientSession` (470). `ElevenLabsHttpTTSService(sample_rate=8000, settings=ElevenLabsHttpTTSSettings(model=..., voice=...))`. **Only model and voice are set**: `model=os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2")` (479), `voice=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")` (480). The settings object is built once per call, so a read here is a read "at call start". |
| `agent/bot.py` greeting | 490-498 | `build_initial_messages(...)` (490) and `greeting = messages[-1]["content"]` (493) come **after** the TTS block and **inside the same `async with` block**. A variable defined in the TTS block is therefore in scope where 018 builds its greeting. |
| `agent/bot.py` header and import | 31-37, 80-86 | The HTTP service was chosen because the WebSocket service "went unhealthy after the first turn" on this Hetzner/Docker setup with no error logged (80-85). |
| `agent/bot.py` `run_bot` order | 359-636 | `check_env` (371), handshake (380), KB (407), transport, STT, LLM, **TTS block (470-482)**, messages (490), models built (501), observers (529-541), **`make_redis_client()` at 556**, `PipelineWorker` (577). No Redis client exists yet at the TTS block. |
| `agent/bot.py` `_call_timing`, `CallTimingObserver` | 307-356 | Existing `call timing:` format (`conn`, `t_ms`). `conn_id` and `ws_connected_at` are `run_bot` keyword arguments (359-364), `None` in tests. |
| `agent/demo_guard.py` `read_config`, `_redis_call` | 120-153; 25, 45 | The `demo:config` style: `HGETALL` on a hash, per-field parse, an invalid value gives WARNING `Invalid demo:config value for {}; using default` and the default, Redis call capped by `wait_for` (2.0 s). `demo_guard` raises `GuardUnavailable` when Redis is down, because rate limits are a safety boundary. **The voice must do the opposite**: Redis down means fall back and carry on. |
| `agent/tools.py` `make_redis_client` | 500-535 | `from_url` with `socket_connect_timeout=1.0`, `socket_timeout=2.0`, ping capped at 1.0 s, returns `None` on any failure. 015 measured `redis_ms=2` per call on the VPS (`after-015-timing.log`), so a second short-lived connection costs about 2 ms. |
| `agent/server.py` `lifespan`, `_refresh_project_kb_forever` | 85-96, 100-136; 81 | 015's KB refresh: one `asyncio.create_task` (122), a sleep loop, `try/except Exception` logging a WARNING with the class name only, cancelled and awaited in `finally` (128-130). The shared `aiohttp.ClientSession` is `app.state.session` (108). The keep-warm loop copies this shape. |
| `agent/log_scrub.py` `scrub` | 1-33 | Removes Redis URLs, env values whose names end `_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD` (8+ chars), JWTs, `sk-` keys, Bearer tokens, masks phone shapes. `ELEVENLABS_API_KEY` would be scrubbed; `ELEVENLABS_VOICE_ID` is a public id, not scrubbed. A 20-character alphanumeric id cannot match the phone patterns (they need a non-alphanumeric boundary). |
| Pipecat `services/elevenlabs/tts.py`, settings | 160-181, 235-256 | `build_elevenlabs_voice_settings` builds the `voice_settings` payload from the five fields and drops any that are `None`, returning `None` if none are given (so an unset config sends no `voice_settings`, exactly as today). `ElevenLabsHttpTTSSettings` also has `optimize_streaming_latency`, sent as a query parameter (1407-1409). |
| Pipecat `tts.py`, `run_tts` | 1348-1522 | POSTs to `/v1/text-to-speech/{voice}/stream/with-timestamps` (1365) with `output_format=pcm_8000` (1405). A non-200 yields an `ErrorFrame` (1419): **the caller hears nothing for that sentence.** |
| **B5: Pipecat `tts.py`, `previous_text`** | 63-66, 1374-1375, 1512-1517, 1253-1258, 1275-1284 | `ELEVENLABS_CONTEXT_UNSUPPORTED_MODELS = {"eleven_v3"}` is the **only** exclusion. `previous_text` is sent for every sentence after the first of a turn whenever the model is not in that set. The file contains **no mention of v4** (`grep v4` finds nothing; Pipecat 1.5.0 predates `eleven_v4_turbo` in this code). So for `eleven_v4_turbo` Pipecat **will send** `previous_text`; whether the API accepts it on v4 is **UNVERIFIED**. If it rejects it, the second sentence of every turn on v4 would be silent. This is why exit test B starts with a probe. |
| **B4: Pipecat text-filter hook** | `services/tts_service.py` 179, 219, 294-295, 922, 1043-1045; `elevenlabs/tts.py` 1094, 1190-1196; `utils/text/base_text_filter.py` 19-65 | `TTSService.__init__` takes `text_filters: Sequence[BaseTextFilter]`; `ElevenLabsHttpTTSService.__init__` passes `**kwargs` through to it, so `text_filters=[...]` works. In `_push_tts_frames` each filter's `filter(text)` runs on the aggregated text just before it goes to TTS (1043-1045), and a result that is only whitespace is skipped (the non-streaming branch right after). `BaseTextFilter` has one abstract method, `async filter(self, text) -> str`. A tag-stripping filter is about six lines. Sentence aggregation is the default here, so a whole `[tag]` arrives inside one sentence. Not run. |
| `agent/week2_latency_observer.py`, `tools/latency_report.py` | 54-75; 91, 152, 194 | The events log carries `[turn N] ElevenLabsHttpTTSService#k: TTFB 0.xxxs` lines. `latency_report.py` prints "greeting TTS first audio ms" per call. They do not name the model, so the `voice config:` line is what ties a call to its model. |
| `/Users/vansh/Desktop/SALES AGENT/tts_bench.py` | whole file | The founder's benchmark: inside the container, `urllib` (a new connection for every request), **`ulaw_8000`** (production asks for `pcm_8000`), **no `voice_settings`**. Its output is not in the repo. |
| **B1: ElevenLabs "What is Eleven v4" help page** | fetched 25 Oct by me | Confirms the two sentences the founder quoted: "Both variants use two voice settings: Stability and Similarity." and "Style and Speed sliders are not available in Eleven v4, and SSML is not supported." It does not mention Speaker Boost, `previous_text`, WebSocket or bidirectional streaming, `apply_text_normalization` or `optimize_streaming_latency`. It does not say outright that audio tags work (it lists "audio tags" among the improvements over v3). **It describes the web-app sliders, not the API.** Whether the API rejects or ignores `style` and `speed` on v4 is UNVERIFIED, which is exactly why they are dropped. |
| `.env.template` | 21-22 | `ELEVENLABS_API_KEY=` and `ELEVENLABS_MODEL=`. `ELEVENLABS_VOICE_ID` is not in the template. |

**Findings that shaped the design:**

1. **Production baseline settled (founder ran step 0 on 25 Oct):** the container reports `ELEVENLABS_MODEL=eleven_flash_v2_5` and `ELEVENLABS_VOICE_ID=GQrVSQduiFCVTMHGavV5`. The voice is not the code default `21m00Tcm4TlvDq8ikWAM`, and the code default model (`eleven_turbo_v2`, `bot.py:479`) is not what runs. So "no override" means exactly what env gives, and the code defaults stay untouched. Not in the founder's paste: the `HGETALL voice:config` check (it is repeated in the exit test).
2. **The HTTP service is not memoryless.** It sends `previous_text` for later sentences of a turn. It lacks request-id stitching and `next_text`. Whether that explains the tone shifts is UNVERIFIED (matters for 021).
3. **`bot.py` has no Redis client at the TTS block**, handled with a second short-lived connection (agreed).
4. **A model that rejects what we send silences the call.** Two ways to trigger it are now known: a wrong model or voice id (shape checks and the allow-list cover the model), and v4 settings or `previous_text` that v4 does not accept (the per-model send rule covers settings; `previous_text` is covered by the probe and, if it fails, by the follow-up under Risks).

**Not verified:**

- Anything on the VPS beyond the two values the founder pasted: no SSH (rule), no `.env` read. The `nxlyr_redis` container name for `redis-cli` comes from the 015 spec; `appendonly` persistence of the override comes from `docker-compose.yml`, not observed.
- Which voice settings **Flash v2.5** honours: `stability`, `similarity_boost` and `speed` are sent and may be honoured or ignored. UNVERIFIED. The founder's web app showed no style control on Flash, so `style` on Flash may also be ignored or unavailable; the founder's Flash set leaves it out. Exit test B is where this shows, together with the probe.
- Whether `eleven_v4_turbo` accepts `use_speaker_boost`, `previous_text`, `optimize_streaming_latency`, or rejects/ignores `style` and `speed` at the **API**. UNVERIFIED; the probe (exit test step 2) answers it with status codes. A 200 means accepted **or ignored**, which a status code cannot separate; only a 4xx proves rejection.
- That `eleven_v4_turbo` is the exact model id. It comes from the founder's bench (`tts_bench.py:36`), reported working; I have not called the API.
- **The cost per character of `eleven_v4_turbo` against Flash on the founder's plan** (the founder checks the ElevenLabs pricing page), what a keep-warm request costs on either, the plan's concurrency limit, and how long a voice stays warm (exit test C measures the last).
- The 144, 148 and 162 ms bench figures (output not in the repo, and `ulaw_8000` without settings).
- Whether v4 Turbo's bidirectional streaming exists only over WebSocket, as the founder states; the help page I fetched does not mention it, so I could not confirm it.
- Whether sending only some of the voice settings makes ElevenLabs fill the rest from the voice's saved settings or from global defaults.
- No test was run in this session; I wrote no code.

## Design (files to touch and why)

### New: `agent/voice_config.py`

One small module, imported by `bot.py` and `server.py`.

**Fields and validation** (one table in code; one loop applies it to both Redis and env, so the two sources cannot drift):

| Field | Env name | Accepted | Today's value when nothing is set |
| --- | --- | --- | --- |
| `provider` | `TTS_PROVIDER` | exactly `elevenlabs` | `elevenlabs` |
| `model` | `ELEVENLABS_MODEL` | `eleven_flash_v2_5`, `eleven_v4_turbo`, `eleven_turbo_v2_5`, `eleven_turbo_v2`, `eleven_multilingual_v2` (founder's list; `eleven_v3_conversational` is not on it) | `eleven_turbo_v2` (code default, `bot.py:479`); production's env gives `eleven_flash_v2_5` |
| `voice` | `ELEVENLABS_VOICE_ID` | 15 to 40 characters, letters and digits only | `21m00Tcm4TlvDq8ikWAM` (`bot.py:480`); production's env gives `GQrVSQduiFCVTMHGavV5` |
| `stability` | `ELEVENLABS_STABILITY` | finite float 0.0 to 1.0 | unset (not sent) |
| `similarity_boost` | `ELEVENLABS_SIMILARITY_BOOST` | finite float 0.0 to 1.0 | unset |
| `style` | `ELEVENLABS_STYLE` | finite float 0.0 to 1.0 | unset |
| `use_speaker_boost` | `ELEVENLABS_USE_SPEAKER_BOOST` | `true` / `false` / `1` / `0`, any case | unset |
| `speed` | `ELEVENLABS_SPEED` | finite float 0.7 to 1.2 | unset |
| `optimize_streaming_latency` | `ELEVENLABS_OPTIMIZE_STREAMING_LATENCY` | integer 0 to 4 | unset (allowed, left unset; not sent) |
| `keepwarm_seconds` | none (Redis only) | integer 0, or 60 to 3600; 0 turns keep-warm off | 240 |

**Which fields are sent depends on the model (B2).** A constant `SENT_FIELDS_BY_FAMILY`:

| Model | Sent (if resolved to a value) | Dropped even if set |
| --- | --- | --- |
| any `eleven_v4*` (`is_v4(model)` = `model.startswith("eleven_v4")`) | `stability`, `similarity_boost` | `style`, `speed`, `use_speaker_boost`, `optimize_streaming_latency` |
| every other model | all five voice settings and `optimize_streaming_latency` | none |

Reasons, stated plainly: if v4 rejects an unknown setting with a non-200, the caller hears silence; a field that is merely ignored is harmless; we do not know which it is, so for v4 we send only what ElevenLabs' own page says v4 has. `use_speaker_boost` is dropped because the page does not mention it and I cannot confirm v4 accepts it; if the probe shows it is accepted, adding it to the v4 set is a one-line follow-up, not part of this PR. I extend the same drop to `optimize_streaming_latency` (a query parameter, not a voice setting, but the same silent-failure mode, and it stays unset in practice); object if you want it sent on v4. For non-v4 models, nothing is dropped, so Flash with the founder's settings behaves as a straight pass-through.

**Functions:**

- `resolve(override, environment) -> VoiceConfig` is pure. Per field: the Redis value if present and valid, else the env value if present and valid, else the default. A bad value logs one `logger.warning("Invalid voice:config value for {}; using fallback", field)`, naming the **field only, never the value or any key**, in the style of `demo_guard.py:147`. Fallback is per field, so one typo does not discard the others. A field name in the hash that is not in the table also logs a WARNING (otherwise `HSET voice:config stabilty 0.5` silently does nothing). The resolved `VoiceConfig` keeps what was set; the drop is applied afterwards by `sent_fields(cfg)` and `dropped_fields(cfg)`, so the log line can show both.
- `async read_override(redis_client=None)` makes a short-lived client with `tools.make_redis_client()` when none is given, runs `HGETALL voice:config` under one `asyncio.wait_for(..., 1.0)` covering connect and read, closes the client in `finally`, returns `None` on a missing `REDIS_URL`, any exception or the timeout (WARNING with the exception class name only). It never raises.
- `to_settings(cfg) -> ElevenLabsHttpTTSSettings` builds the settings with `model` and `voice` always, plus each field in `sent_fields(cfg)`. With no override and the production env, the object is field for field what `bot.py:478-481` builds today (`model=eleven_flash_v2_5`, the voice), and Pipecat sends no `voice_settings` and no `optimize_streaming_latency`.
- `log_line(cfg, conn_id) -> str`: `voice config: conn=<hex or none> provider=elevenlabs model=<m> voice=<id> stability=<x|unset> similarity_boost=<x|unset> style=<x|unset> use_speaker_boost=<x|unset> speed=<x|unset> optimize_streaming_latency=<n|unset> overrides=<comma list of fields taken from Redis, or none> dropped=<comma list, or none>`. The setting values shown are the ones **sent**; a dropped field shows `unset` there and appears in `dropped=`. It reads the resolved config only and never touches `os.environ`, so a key cannot get in by construction.
- `StripTagsFilter(BaseTextFilter)` (B4): `async filter(text)` removes `\[[^\[\]]{1,40}\]` and collapses the resulting double spaces. It exists so that audio tags such as `[warm]` can never be spoken aloud as words. `tts_filters(cfg)` returns `[]` for a v4 model and `[StripTagsFilter()]` otherwise. Today only 018's greeting can contain tags, and 018 guards it already, so this is a second layer. The system prompt's own bracketed headers (`[CORE RULES]`, `[CURRENT DATE]`, `prompt.py:103-141`) would also be stripped if the model ever echoed one, which is harmless. With no brackets in the text, the filter returns the text unchanged, so "nothing changes with no override" holds (tested).
- `async keep_warm_once(session, cfg, api_key) -> tuple[bool, int]` mirrors Pipecat's `run_tts` request: `POST {base}/v1/text-to-speech/{voice}/stream/with-timestamps?output_format=pcm_8000[&optimize_streaming_latency=N]`, header `xi-api-key`, JSON `{"text": "<3 characters>", "model_id": cfg.model, "voice_settings": {...}}` with **the same `voice_settings` the call would send (after the per-model drop)**, so the warmed state is the one the call asks for. It reads the first chunk, records `ttfb_ms`, drains the rest, under a 10 s total timeout (F12). On non-200 it logs `status=<int>` only, never the body. It sends no `previous_text`.

### `agent/bot.py` (inside the TTS block, lines 466-482, plus the import at 86)

- Import, one line near the other local imports (104-111): `from voice_config import is_v4, log_line, read_override, resolve, to_settings, tts_filters`.
- Inside the existing `async with aiohttp.ClientSession() as session:`, immediately before `tts = ElevenLabsHttpTTSService(...)`:
  ```
  voice_cfg = resolve(await read_override(), os.environ)
  logger.info(log_line(voice_cfg, conn_id))
  ```
  and the two arguments become `settings=to_settings(voice_cfg)` and `text_filters=tts_filters(voice_cfg)`. `sample_rate=EXOTEL_SAMPLE_RATE` and `api_key` stay as they are.
- **`voice_cfg` is a fixed name** (B3). It stays a local of `run_bot`, in scope for everything after the TTS block in the same `async with` (the greeting at 490-498 is one of those). It must not be renamed by this task or later ones; 018 relies on it.
- **Why a second short-lived Redis connection:** agreed in r1. About 2 ms (`redis_ms=2`), capped at 1.0 s, falls back to env on failure.
- `check_env` (371) already requires `ELEVENLABS_API_KEY`; unchanged.

### `agent/server.py` (lifespan only)

- `_keep_voice_warm_forever(app)` beside `_refresh_project_kb_forever` (85-96), same shape. Each tick: (a) read the override and resolve the config, so it warms **whatever the next call will use**, including after a swap to v4; (b) skip the tick if `keepwarm_seconds` is 0 or `ELEVENLABS_API_KEY` is unset; (c) call `keep_warm_once(app.state.session, cfg, key)` inside `try/except Exception`; (d) sleep `keepwarm_seconds` (re-read every tick, so the off switch takes effect within one interval, no restart).
- In `lifespan` (100-136): one `asyncio.create_task(..., name="voice-keepwarm")` next to `refresh_task` (122-124), cancelled and awaited the same way in `finally` (128-130). It starts with a first tick immediately after startup, so a freshly deployed container warms the voice before the first caller.
- Log lines: `voice keep-warm: ok model=<m> ttfb_ms=<int>` at INFO on every tick (about 360 lines, 36 KB a day; no Docker log rotation, see Risks); on failure `voice keep-warm failed status=<int|none> error_type=<class>` at WARNING, no body, no key, no URL. `ttfb_ms` doubles as an independent warm/cold gauge.
- The keep-warm uses the shared `app.state.session`; calls use their own per-call session (`bot.py:470`). If the cold cost were in the TLS connection, warming a different session would not help. I think it is server-side voice and model state, because `tts_bench.py` opens a fresh connection per request and still measures 144 to 162 ms (if the founder's figures are right). UNVERIFIED; exit test C decides. If C fails, the follow-up is a shared session for calls.

### Other files

| File | Change |
| --- | --- |
| `.env.template` | add the seven new variable names, blank, with one comment line; add `ELEVENLABS_VOICE_ID` (missing today) |
| `agent/test_voice_config.py` (new) | the tests below |
| `AGENTS.md` | one line in Commands for `agent.test_voice_config` |
| `docs/memory/inbox/` | one note with the exit-test result; a correction of `2026-10-24-tts-prosody-http-service-no-request-stitching.md` (finding 2) |

Not touched: `prompt.py`, `log_scrub.py`, `demo_guard.py`, `tools.py`, `ws_auth.py`, `Dockerfile`, `requirements.txt`, nginx, workflows, `test_pipeline.py`.

### Overlap

- **018 (conversation v2.1, being built now), `bot.py`.** The meeting point is the **active voice model**. 018 builds a tagged greeting that it uses only when the active model is a v4 model. Contract for whichever of 018 and 019 merges second:
  - This task defines `voice_cfg` (a `voice_config.VoiceConfig`) in the TTS block, and `voice_config.is_v4(model)`.
  - 018 builds the greeting after the TTS block (around line 490), where `voice_cfg` is in scope, and wires its guard to `is_v4(voice_cfg.model)`.
  - If 018 merges first, 019 rebases and adds nothing to the greeting; 018 then temporarily reads the model another way, and the second merger swaps its guard to `voice_cfg.model`. If 019 merges first, 018 uses `voice_cfg.model` from the start.
  - **`voice_cfg` is not renamed later.**
  - The tag filter is an independent second layer: it strips tags whenever the model is not v4, even if 018's guard were wrong.
- **020 (barge-in), `bot.py`:** edits the user-aggregator and turn lines; my hunks are the import and the TTS block. Whoever merges second rebases.
- **`server.py`:** 015 edited `lifespan`; mine adds a task beside its task.

## Data touched

- **Redis, new key `voice:config` (a hash), read only by the app** (`HGETALL`), written only by the founder with `redis-cli`. Fields as in the table above. No TTL: it persists until cleared, and survives restarts because `docker-compose.yml` runs Redis with `appendonly yes` on the `redis_data` volume (not observed). Existing keys (`demo:config`, `demo:kill`, `demo:*`, `ws:*`, call session hashes) are not touched.
- **ElevenLabs API:** one extra POST every 240 s while the server is up (about 360 a day), each of about 3 characters. Billing UNVERIFIED (see Not verified).
- **No tables, columns or migrations. No SQL, none executed.** Supabase is not touched.
- **Logs:** `voice config:` and `voice keep-warm` lines hold model and voice ids, numbers and field names. No key, no URL, no response body, no phone, no name.

## Acceptance tests (automated)

New `agent/test_voice_config.py`, `unittest`, `IsolatedAsyncioTestCase`, no network, in the style of `test_startup_timing.py`. Command (from the worktree root):

```
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_voice_config agent.test_startup_timing agent.test_turn_release agent.test_prompt agent.test_ws_auth agent.test_log_hygiene agent.test_demo_guard agent.test_kb_loader
(cd agent && "$PY" -c "import server, week2_latency_observer")
```

| # | Test | Proves |
| --- | --- | --- |
| V1 | No override, empty environment: `resolve` gives model `eleven_turbo_v2`, voice `21m00Tcm4TlvDq8ikWAM`, every setting unset, `overrides=none`, `dropped=none`. With the production environment (`ELEVENLABS_MODEL=eleven_flash_v2_5`, `ELEVENLABS_VOICE_ID=GQrVSQduiFCVTMHGavV5`): those values. In both cases `to_settings` equals `ElevenLabsHttpTTSSettings(model=..., voice=...)` field for field, and `build_elevenlabs_voice_settings` on it returns `None`. | Merge with no override changes nothing the caller can hear (goal 3). |
| V2 | Precedence per field: Redis beats env beats default, with a mix (model from Redis, voice from env, speed from default). | Goal 2. |
| V3 | Table-driven invalid values, one per row: `stability` `1.5`, `-0.1`, `abc`, `nan`, `inf`, empty; `speed` `0.5`, `2`; `use_speaker_boost` `maybe`; `optimize_streaming_latency` `5`, `1.5`; `model` not in the allow-list (including `eleven_v3_conversational`); `voice` with a space or 3 characters; `provider` `openai`; `keepwarm_seconds` `30`. Each gives the next source's value, exactly one WARNING naming the field, **and the warning text does not contain the bad value**. The other fields in the same hash still apply. | Invalid values fall back and never break a call. |
| V4 | An unknown field name in the hash (`stabilty`) logs one WARNING naming it and changes nothing. | A typo cannot pass silently. |
| V5 | `read_override`: `REDIS_URL` unset, a client whose `hgetall` raises, and a client whose `hgetall` sleeps 10 s all return `None` in under 1.5 s, log a WARNING with the exception class only, and close the client. | Redis trouble never breaks or delays a call. |
| V6 | Drive `run_bot` as `test_startup_timing` does, with `ElevenLabsHttpTTSService` patched to capture its `settings` and `text_filters`. With a fake override `{"model": "eleven_flash_v2_5", "stability": "0.45", "similarity_boost": "0.75", "speed": "1.0"}`, the captured settings hold exactly those. With none, they equal V1's. The `voice_cfg` name is checked by reading the source of `run_bot` (`inspect.getsource` contains `voice_cfg = resolve(`), and by a patched `build_initial_messages` that records `sys._getframe(1).f_locals` to assert `voice_cfg` is already a local of `run_bot` when the greeting is built. | The TTS block uses the resolved config; the contract name holds. |
| **V7 (B2)** | The same drive with an override `{"model": "eleven_v4_turbo", "stability": "0.5", "similarity_boost": "0.75", "style": "0.3", "speed": "0.95", "use_speaker_boost": "true"}`: the captured settings carry `stability` and `similarity_boost` and **no `style`, no `speed`, no `use_speaker_boost`**; `build_elevenlabs_voice_settings` on them gives exactly `{"stability": 0.5, "similarity_boost": 0.75}`; the log line contains `dropped=style,speed,use_speaker_boost` (field order fixed in code and asserted). The same override with `eleven_flash_v2_5` drops nothing and sends all of them (`dropped=none`). With `optimize_streaming_latency` set, it is dropped on v4 and sent on Flash. | A v4 call cannot carry a setting v4 may reject. |
| V8 | In V6 and V7, exactly one `voice config:` line per call, matching `^voice config: conn=(?:[0-9a-f]{6}\|none) provider=elevenlabs model=\S+ voice=[A-Za-z0-9]+ (?:\w+=\S+ )*overrides=\S+ dropped=\S+$`. With `ELEVENLABS_API_KEY` set to a distinctive value in the environment, that value appears in no captured log. `log_scrub.scrub(line) == line`. | Goal 4: one line, no key, nothing for the scrubber to remove. |
| **V9 (B4)** | `tts_filters`: empty for `eleven_v4_turbo`; one `StripTagsFilter` for `eleven_flash_v2_5`, `eleven_turbo_v2_5`, `eleven_turbo_v2`, `eleven_multilingual_v2`. `await StripTagsFilter().filter(...)`: `"[warm] Hi, this is Aarya. [reassuring] It is a plan."` becomes `"Hi, this is Aarya. It is a plan."`; text with no brackets is returned **unchanged, byte for byte** (the real greeting from `build_initial_messages`, plus a few ordinary sentences); a string that is only a tag becomes empty or whitespace; `"[CURRENT DATE]"` is removed. The captured `text_filters` in V6 and V7 are the ones above. | Tags are never spoken on a non-v4 model, and the filter does not change anything else (goal 3). |
| V10 | `keep_warm_once` with a fake session: it POSTs to `.../v1/text-to-speech/<voice>/stream/with-timestamps` with `output_format=pcm_8000`, `optimize_streaming_latency` only when sent, payload `model_id` and `voice_settings` equal to what a call would send for that model (so for v4: stability and similarity only), no `previous_text`, text of at most 5 characters, and the key only in the `xi-api-key` header. A 500, a 401, a raised `ClientError` and a hang past the 10 s cap each return `(False, ...)`, log a WARNING without the response body or the key, and raise nothing. | The warm-up asks for what a call asks for, and fails safe. |
| V11 | `_keep_voice_warm_forever` with a patched clock and fake `keep_warm_once`: it fires a first tick before the first sleep; honours a changed `keepwarm_seconds` on the next tick; makes no request when `keepwarm_seconds` is 0 or the API key is unset; keeps looping after a failed tick; `lifespan` shutdown cancels it with no pending-task warning. | Keep-warm runs, is switchable without a restart, and cleans up. |
| V12 | Regression: all suites in the command above pass; import smoke passes; `git diff origin/main -- agent/prompt.py agent/log_scrub.py agent/demo_guard.py agent/tools.py` is empty. | Nothing else moved. |

The builder must show V1, V6 and V7 pass on the branch; V1's and V6's "no override" cases are the merge-safety test.

## Exit test (what I do by hand on real calls, with exact commands)

Tags: 🧑 YOU does it, 👀 VERIFY you check it. The agent does not SSH. Run all steps in one terminal tab so `T0` survives. Same script and same phone for every call. Do not edit the VPS `.env` while calls are in flight (it recreates Redis; `hot.md`). Files go in `/Users/vansh/Desktop/SALES AGENT/exit-019-<date>/`.

**Step 0 (done 25 Oct, recorded):** `ELEVENLABS_MODEL=eleven_flash_v2_5`, `ELEVENLABS_VOICE_ID=GQrVSQduiFCVTMHGavV5`. Before the merge, 🧑 add the one check missing from the paste, and copy the container's latency files off (they are lost on deploy), as in the 015 spec step 5:
```
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL voice:config"
```
👀 It prints nothing.

**A. Merge with no override: 3 calls, nothing changed**

1. 🧑 Merge is the human's. 👀 Check container health twice, a few seconds apart. `T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$T0"`
2. 🧑 Place 3 calls with your usual script.
3. 👀 One line per call and the keep-warm ticks:
   ```
   ssh nxlyr-vps "docker logs nxlyr_agent --since $T0 2>&1 | grep -E 'voice config|voice keep-warm'"
   ```
   Pass: exactly 3 `voice config:` lines, each `model=eleven_flash_v2_5 voice=GQrVSQduiFCVTMHGavV5`, every setting `unset`, `overrides=none dropped=none`; `voice keep-warm: ok` lines present (the first one right after the deploy). By ear, nothing changed against calls you remember. The first call after a deploy is cold unless the startup keep-warm tick ran first; the tick lines show which.

**B. `eleven_v4_turbo` against Flash with your settings: 5 and 5**

4. 🧑 **Pre-flight probe (once, before any v4 call).** It answers what the docs do not: does v4 Turbo accept `previous_text`, `use_speaker_boost`, `style`, `speed`? It runs inside the container, reads the key from the container's own environment and never prints it, and prints only model, case, HTTP status, time and (on error) the first 120 characters of ElevenLabs' error message. Save this as `probe.py` on your Mac and run it (10 requests of about 33 characters each):
   ```
   import json, os, time, urllib.error, urllib.request

   KEY = os.environ["ELEVENLABS_API_KEY"]
   VOICE = os.environ["ELEVENLABS_VOICE_ID"]
   URL = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/stream/with-timestamps?output_format=pcm_8000"
   BASE = {"stability": 0.5, "similarity_boost": 0.75}
   CASES = [
       ("stability+similarity", {"voice_settings": BASE}),
       ("previous_text", {"previous_text": "Hi, this is Aarya."}),
       ("use_speaker_boost", {"voice_settings": {**BASE, "use_speaker_boost": True}}),
       ("style", {"voice_settings": {**BASE, "style": 0.3}}),
       ("speed", {"voice_settings": {**BASE, "speed": 0.95}}),
   ]
   for model in ("eleven_v4_turbo", "eleven_flash_v2_5"):
       for name, extra in CASES:
           body = json.dumps({"text": "It is a construction linked plan.", "model_id": model, **extra}).encode()
           req = urllib.request.Request(URL, data=body, headers={"xi-api-key": KEY, "Content-Type": "application/json"})
           t0 = time.perf_counter()
           try:
               resp = urllib.request.urlopen(req, timeout=20)
               resp.read(1)
               code, note = resp.status, "accepted"
               resp.read()
           except urllib.error.HTTPError as e:
               code, note = e.code, "REJECTED " + e.read()[:120].decode("utf-8", "replace")
           except Exception as e:  # noqa: BLE001 - class name only
               code, note = 0, "ERROR " + type(e).__name__
           print("%-20s %-22s %s %4d ms  %s" % (model, name, code, int((time.perf_counter() - t0) * 1000), note))
           time.sleep(1)
   ```
   ```
   ssh nxlyr-vps "docker exec -i nxlyr_agent python -" < probe.py | tee probe-result.txt
   ```
   (The script is syntax-checked; it has not been run against the API.)
5. 👀 Read the probe. A 200 means accepted **or ignored**; only a 4xx proves rejection.
   - **`eleven_v4_turbo` + `previous_text` rejected (4xx): stop.** Pipecat 1.5.0 would send it on every second sentence of a turn, so v4 calls would go silent mid-turn. Record it; v4 waits for task 021 (founder decision: no patch to Pipecat) and production stays on Flash. Exit test B then continues Flash-only.
   - `style` or `speed` rejected on v4: confirms the drop was right. Accepted: it was merely cautious; it stays dropped in this PR.
   - `use_speaker_boost` accepted on v4: noted as a one-line follow-up, not added here.
   - The same cases on Flash show which settings Flash tolerates; that is a status code, not proof it honours them.
6. 🧑 Set the override for the **Flash** set (Flash gets stability 0.45, similarity_boost 0.75, speed 1.0, no style), read it back:
   ```
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET voice:config model eleven_flash_v2_5 stability 0.45 similarity_boost 0.75 speed 1.0"
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL voice:config"
   ```
   and the command for the **v4 Turbo** set (v4 gets stability and similarity_boost only; put in the numbers from your web-app session):
   ```
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET voice:config model eleven_v4_turbo stability <V4_STABILITY> similarity_boost <V4_SIMILARITY>"
   ```
   `speed 1.0` stays in the hash when you swap to v4; that is intended: the v4 call's line must show `dropped=speed`, which proves the drop in production. The new value applies from the **next** call. Never swap during a call.
7. 🧑 Place one v4 call first, long enough for **at least three bot turns** (so a second sentence of a turn is spoken). 👀 Its `voice config:` line shows `model=eleven_v4_turbo`, your two numbers, `style` and `speed` `unset`, `overrides=` listing what you set, `dropped=speed`. 👀 There is no silence after the first sentence of a turn, and:
   ```
   ssh nxlyr-vps "docker logs nxlyr_agent --since $T0 2>&1 | grep -ci 'elevenlabs api error'"
   ```
   prints 0. (UNVERIFIED how Pipecat words the error line; the count is a hint, the ear is the check.) If silent or non-zero, run `DEL voice:config` (step 11) and stop.
8. 🧑 **Alternate the sets**, so idle time and time of day do not confound them: v4, Flash, v4, Flash, and so on, 5 calls each, placed within about 4 minutes of each other. Swap with the two `HSET` commands in step 6.
9. 🧑 Score by ear, per call, against your script, in your notes:
   - Overall naturalness 1 to 10.
   - **v4 calls only, two extra yes/no marks: does the greeting's tone hold across its sentences, and does the closing line fall?** (Score them on Flash too if you can, for comparison.)
   - Pronunciation notes, especially "crore" and "Aetheria". A mispronunciation there is not fixed in this task; it becomes the pronunciation-dictionary follow-up (B7).
10. 🧑 Pull the figures:
    ```
    ssh nxlyr-vps "docker logs nxlyr_agent --since $T0 2>&1 | grep -E 'voice config|voice keep-warm|call timing'" > after-voice.log
    grep -cE '[0-9]{7,}' after-voice.log
    ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/"
    scp nxlyr-vps:/tmp/section6_real_call_events.log ./events.log
    ssh nxlyr-vps "rm -f /tmp/section6_real_call_events.log"
    python3 /Users/vansh/Desktop/SALES\ AGENT/tools/latency_report.py ./events.log --from-call 0 --md
    ```
    👀 Join by order: the n-th `voice config:` line is the n-th call in `latency_report.py`'s "greeting TTS first audio ms" column (the events log does not name the model, so keep the order). Compare v4 5 against Flash 5: greeting TTS p50 and max, your ear scores, the tone and closing-line marks. The `[0-9]{7,}` count must be 0.
11. 🧑 Decide the model and settings. Leave the winning values in `voice:config` as the live setting (it persists across restarts), or put the model in the VPS `.env` yourself. To go back to exactly today's behaviour:
    ```
    ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL voice:config"
    ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL voice:config"
    ```
    (the second must print nothing). To drop a single field: `HDEL voice:config speed`.

**C. Keep-warm: one call after 30 or more minutes idle**

12. 🧑 After step 11, place no call for at least 30 minutes (45 is better). Do not restart the container. Keep-warm warms whatever model `voice:config` then holds, so test C on the model you chose in step 11.
13. 👀 During the wait:
    ```
    ssh nxlyr-vps "docker logs nxlyr_agent --since $T0 2>&1 | grep 'voice keep-warm' | tail -15"
    ```
    Pass: a line about every 4 minutes, all `ok`, `ttfb_ms` staying near 160 (a drift to 500 or more means the warm-up does not keep the voice warm, whatever the call says).
14. 🧑 Place one call. Pull `events.log` again as in step 10 and run `latency_report.py`.
15. 👀 Pass: that call's greeting TTS first audio is **250 ms or less** (founder-agreed pass line), against 537 ms after 30 idle minutes before this task.
16. 🧑 Switch keep-warm off at any time, no deploy: `ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET voice:config keepwarm_seconds 0"`; back to the default: `HDEL voice:config keepwarm_seconds`.

**Command reference:**

```
SET   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET voice:config model eleven_v4_turbo stability <S> similarity_boost <SIM>"
READ  ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL voice:config"
CLEAR ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL voice:config"
```

Where to look: lines from the app's logger (`voice config:`, `voice keep-warm`, warnings) are in `docker logs nxlyr_agent`; only the `[turn N]` latency lines are in the events log.

### What I compare

| Measure | Before (known) | After (to fill in) | Pass |
| --- | --- | --- | --- |
| `voice config:` lines, no override | none | 3 of 3 calls, Flash, voice `GQrV...`, settings unset | exactly as stated |
| Ear check, no override | your memory of prior calls | 3 calls | nothing changed |
| Probe: v4 Turbo and `previous_text` | UNVERIFIED | status | not rejected (else stop, step 5) |
| Probe: v4 `style`, `speed`, `use_speaker_boost` | UNVERIFIED | status each | recorded; the drop stays either way |
| v4 call line shows the drop | n/a | `dropped=speed`, no style or speed sent | every v4 call |
| "ElevenLabs API error" lines during B | n/a | 0 | 0 |
| Greeting TTS first audio, Flash with your settings | about 160 ms warm | p50 and max of 5 | reported |
| Greeting TTS first audio, v4 Turbo | 148 ms bench (UNVERIFIED: `ulaw_8000`, no settings) | p50 and max of 5 | reported; you decide |
| Ear: naturalness, v4 against Flash | n/a | 5 and 5 | your decision |
| Ear: tone holds across the greeting's sentences (v4) | n/a | y/n per call | your decision |
| Ear: closing line falls (v4) | n/a (014 call 15: no fall) | y/n per call | your decision |
| Keep-warm ticks over the idle wait | none | all `ok`, `ttfb_ms` near 160 | as stated |
| Greeting TTS after 30+ min idle | 537 ms (30 min), 744 to 802 ms (2 h) | 1 call | 250 ms or less |
| Leak count (`[0-9]{7,}` on the log excerpt) | 0 | 0 | 0 |
| Cost per character, v4 Turbo against Flash | UNVERIFIED | you check the pricing page | recorded |

## Risks and rollback

| Risk | Likelihood | Effect | Mitigation |
| --- | --- | --- | --- |
| **v4 rejects `previous_text`** (Pipecat sends it for any model but `eleven_v3`) | unknown | Second and later sentences of each turn silent on v4 | The probe (step 4-5) tests it before any v4 call. If rejected: stop, `DEL voice:config`, v4 waits for task 021, we stay on Flash (founder decision, no Pipecat patch). |
| A well-formed but non-existent voice id is set | medium (hand-typed) | Calls connect, the caller hears silence | The model is checked against the allow-list; a voice id can only be shape-checked. The keep-warm tick (within 4 minutes) logs `status=`. Step 7 is one call after each change. `DEL voice:config` fixes it in seconds. |
| v4 gets a setting it rejects | designed out | Silence | Only `stability` and `similarity_boost` are sent on any `eleven_v4*` model (V7). |
| Flash ignores some settings | real | Settings do nothing audibly | UNVERIFIED which; the log line reports what is **sent**, not what is honoured. Exit test B and the probe show it. |
| The tag filter removes something spoken | very low | A bracketed word dropped on a non-v4 model | Today no spoken text contains brackets (prompt headers only); V9 proves unchanged output without brackets. |
| Override left set after a test | likely | A test voice reaches real demo callers days later | The key persists across restarts. Every `voice config:` line shows `overrides=`; step 11 makes clearing part of the test. |
| Keep-warm costs characters, or hits a concurrency limit while a call is live | low | Small bill; one extra concurrent request for under a second | About 360 requests a day of about 3 characters. Billing UNVERIFIED, so the off switch (`keepwarm_seconds 0`) exists. |
| Keep-warm does not help | possible | The 640 ms stays | Exit test C measures it; `ttfb_ms` in the tick lines is the gauge. A negative result is reported; the follow-up is a shared session for calls. |
| Keep-warm lines add log volume | certain, small | About 36 KB a day; no Docker log rotation | Accepted; log only changes after the first week if it matters. |
| The second Redis connection delays pickup | very low | At most 1.0 s if Redis is down, 2 ms normally | Cap of 1.0 s, falls back to env. |
| `bot.py` / `server.py` conflicts with 018, 020 | likely | Rebase work | Small hunks; the `voice_cfg` contract is written down (Overlap). |

**Rollback:** no data or schema to undo. No-deploy rollbacks: `DEL voice:config` returns every field to env and code defaults; `HSET voice:config keepwarm_seconds 0` stops the warm-up. Full rollback: revert the merge commit on `main` and let `deploy.yml` redeploy (🧑, `git pull` and `docker compose up -d --build` together, CONSTRAINTS rule 2). A stale `voice:config` key is harmless once the code is reverted.

## Open questions for me

**Answered in r1 and recorded (no action):**

1. WebSocket service: not in this task. Proposed as **task 021**: a measured comparison of `ElevenLabsHttpTTSService` and `ElevenLabsTTSService` (greeting TTFB, a 20-minute soak for the silent-unhealthy failure noted at `bot.py:80-85`, an ear test), with a `transport=http|websocket` field in `voice:config` so the A/B is also one command. **Note for 021: per the founder, v4 Turbo's bidirectional streaming is only available over WebSocket, so 021 is where that benefit gets tested.** (I could not confirm this claim: the ElevenLabs v4 help page does not mention it.) 021 also settles whether `previous_text` helps the tone shift (finding 2).
2. Baseline: "no override" means exactly what the container's env and code defaults give today; the code default is not changed. Step 0 confirmed Flash and `GQrVSQduiFCVTMHGavV5`.
3. `provider`: kept as a validated field that accepts only `elevenlabs`.
4. Model allow-list: `eleven_flash_v2_5`, `eleven_v4_turbo`, `eleven_turbo_v2_5`, `eleven_turbo_v2`, `eleven_multilingual_v2`. Not `eleven_v3_conversational`.
5. Redis: a second short-lived connection inside the TTS block.
6. Speed 0.7 to 1.2.
7. Keep-warm 240 s; exit test C pass line 250 ms or less.
8. `optimize_streaming_latency`: allowed, left unset.

**Answered in r2 (founder, 2026-10-25, approved):**

9. On v4, drop `use_speaker_boost` and `optimize_streaming_latency` as well as `style` and `speed`. All four are listed on the `voice config:` line as `dropped=`. Speaker boost can join the v4 set later only if the probe shows it is accepted, in a separate change.
10. If the probe shows v4 rejects `previous_text`, **do not patch Pipecat**: v4 waits for 021 and production stays on Flash. (Step 5 and the first Risks row apply this; the "hack that needs your decision" wording there is superseded by this answer.)
11. Pre-merge `HGETALL voice:config` is run by the founder and must print nothing (exit test, step 0).

## Amendments after review (founder-approved)

Added 26 Oct 2026 after three review rounds (`.agent/reports/review-1.md`, `review-2.md`, `review-3.md`). The r2 text above is unchanged; where it differs from this section, this section wins. Merged on top of 018 (`67e3466`).

1. **`log_line` alias in `bot.py`.** 018 already imports `log_line` from `convo_config`. The spec's import line (`from voice_config import ... log_line ...`) would shadow it silently. The voice import is now `from voice_config import log_line as voice_log_line`, and the voice log call uses `voice_log_line`. Tests: the new 018 integration test and 018's own `g01` to `g05` fail if the collision returns.
2. **Two test-helper lines in `agent/test_convo_config.py`.** `run_wired_bot` gains a `voice_override=None` parameter and patches `bot.read_override` with it, so 018's tests do not pick up an unrelated "voice:config unavailable" WARNING from a missing `REDIS_URL`. No assertion of 018 is changed; `assert_called_once_with` on the greeting warning is as it was on `origin/main`.
3. **018's tag guard reads `voice_cfg.model`.** The Overlap section's contract is now wired: `tts_model = voice_cfg.model` replaces the `os.getenv("ELEVENLABS_MODEL", ...)` placeholder 018 left (`bot.py`, the line marked "019: replace"). Test: a Redis override to v4 with an env model of Flash must give the tagged greeting; the test fails if the guard goes back to the env value.
4. **`test_v12` is deleted.** V12's scope-file diff against `origin/main` was a one-time PR check, not a standing test: it would fail on any later branch that legitimately edits `prompt.py` or `tools.py` (018 does). The scope diff is run once and pasted in the PR instead. V12's full-suite and import-smoke commands stay.
5. **Blank env values count as unset, silently.** An env variable that is present but empty (for example the blank lines in `.env.template`) is skipped with no warning. An empty Redis value, and a non-blank invalid env value, still warn as in V3.
6. **Accepted debt (R2-3): two sequential Redis reads at call start.** 018's `convo:config` read (0.5 s cap) and this task's `voice:config` read (1.0 s cap) run one after the other on separate connections. With Redis healthy or refused both are fast; with Redis unreachable pickup can wait about 1.5 s. Not changed in this task; watch `read_ms` in exit test A. A follow-up can read both hashes on one connection.
