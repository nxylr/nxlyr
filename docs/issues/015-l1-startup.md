# 015 — L1 start-up: make pickup-to-first-word fast, and make the cause visible

**Status: APPROVED r2 (founder approved 2026-10-24).**
Worktree `../nxlyr-worktrees/015-l1-startup`, branch `task/015-l1-startup`, from `origin/main` at `ae2aff2` (014 merged).
Covers: audit F06 (blocking KB fetch in an async path), F12 (missing timeouts, on the pickup path), latency audit L1.

## Goal

Cut the time from pickup to the bot's first word from 3 to 6 seconds to **under 2 seconds** (stopwatch, provisional), and make the cause visible in the logs.

**The pass gate (founder, r2): server side, WebSocket connect to first greeting audio sent is 1.5 s or less on the VPS.** The stopwatch figure and the gap (stopwatch minus server side) are reported on every call but are not the gate. If the gap is over 1.5 s, that is an Exotel / VPS-region question for a separate item, not an L1 failure.

Three things the logs cannot say today, and this task adds:

1. When the WebSocket connected (our proxy for pickup).
2. When the greeting was queued, and how long each set-up step before it took.
3. When the first greeting audio was sent.

Facts from the founder's data (`baseline-2026-10-22/`, `exit-011-2026-10-23/`):

| Observation | Value | Source |
| --- | --- | --- |
| Greeting by stopwatch, baseline, calls 1, 4, 7, 10 | 3.0, 3.75, 4.9, 3.8 s | baseline notes.md |
| Greeting's own TTS first audio | about 160 ms (159 to 300) | baseline report |
| Caller speaks first | bot answers in 2.5 to 3 s | exit-011 report, founder's note |
| Caller waits in silence | greeting starts at about 6 s, **unexplained** | exit-011 report, founder's note |
| First call after 13 idle hours | greeting TTS 1,582 ms against about 160 ms | exit-011 report, call 1 |

The spec must explain or test why silence is slower. Section "Why silence may be slower" below does that with four hypotheses, each with the log line or test that settles it.

## Non-goals

- No change to prompt text or turn-release settings. `agent/prompt.py` and the constants at `bot.py:113-121` stay as they are. Gate: `git diff origin/main -- agent/prompt.py` is empty.
- No change to the TTS model or voice (`ELEVENLABS_MODEL`, `ELEVENLABS_VOICE_ID`, `bot.py:400-411`).
- No new phone number, name or secret in any log line. The 004 scrubber (`agent/log_scrub.py`) stays and is not edited.
- Not touching tool semantics (008), caller name or form of address (012), the greeting text (014, merged).
- F12 beyond the pickup path: the Exotel dial, the contact form Supabase insert and the Telegram call in `server.py` (lines 224, 376, 402) get no timeout here. They get their own task (founder, r2).
- No new dependency, no schema change, no nginx or VPS config change.
- Not fixing the Exotel side of the connect (we cannot see it). If the data shows the missing seconds are before the WebSocket connects (gap over 1.5 s), this task reports that and stops; it is a separate Exotel / VPS-region item, not an L1 failure.

## What I read (and what I did not)

All line ranges are in the worktree at `ae2aff2`. Anything not read or not run is marked UNVERIFIED.

| Where | Lines | What it showed |
| --- | --- | --- |
| `agent/server.py` `websocket_endpoint` | 675-748 | `accept()` at 678. Handshake read (`read_start_handshake`, 5 s cap). Redis client built and pinged with a 1.0 s cap at 710. `admission_session` consumes the binding with a 1.0 s cap. `run_bot` is awaited at 743-744. No timestamp is taken anywhere. |
| `agent/server.py` `lifespan` | 82-107 | Creates the shared `aiohttp.ClientSession` and the Telegram settings. **Nothing is preloaded**: no KB, no models. This is where a boot-time preload would go. |
| `agent/server.py` `get_demo_redis_client` | 291-322 | `redis.asyncio.from_url(redis_url, decode_responses=True)` with no socket timeouts. The ping is capped by `wait_for` only when the caller passes `ping_timeout_seconds` (the `/ws` path passes 1.0). The client is cached on `app.state.redis`, so only the first call pays the connect. |
| `agent/bot.py` `run_bot` | 299-525 | Order of work before the pipeline runs: `check_env` (305), `parse_telephony_websocket` (314), **`load_project_kb()` (337, synchronous inside the async function)**, serializer and transport, Deepgram and OpenAI service objects, a **new `aiohttp.ClientSession` per call (399)**, `build_initial_messages` (419), **`_build_user_aggregator_params()` (431)**, pipeline, **`await make_redis_client()` (468)**, `PipelineWorker`. The greeting is queued in `on_client_connected` (483-500) with `append_to_context=False`. |
| `agent/bot.py` `_build_user_aggregator_params` and `build_user_turn_strategies` | 181-255 | `SileroVADAnalyzer()` (253) and `LocalSmartTurnAnalyzerV3(...)` (230-232, called at 237) are **constructed on every call, synchronously, on the event loop**. Each reads an ONNX file and builds an inference session. |
| `agent/kb_loader.py` `load_kb`, `_fetch_kb` | 19-44, 47-93 | Per-process dict cache with a 300 s stale threshold. The call path serves any cached entry regardless of age and never fetches on age; a stale hit logs a WARNING with its age. Only an empty cache falls through to the synchronous REST fetch, which `run_bot` invokes in a worker thread. Server runs one uvicorn process (`Dockerfile:106`, no `--workers`), so a process-level cache is the right place. |
| `agent/tools.py` `make_redis_client` | 498-529 | `from_url` with no timeouts, then `await client.ping()` with none either (521). Returns `None` on any exception, but a hang never raises. A new connection is made for every call. |
| `agent/tools.py` `_set_session_flag` | 140-155 | `hset` (148) and `expire` (152) with no timeout. Not edited here; a client-level socket timeout covers them without touching 008's lines. |
| `agent/ws_auth.py`, `agent/demo_guard.py` | 13-17; 25-26, 122, 237, 282 | The repo already has the house values: Redis 1.0 s (`ws_auth`) and 2.0 s (`demo_guard`), Supabase 5.0 s. I reuse these numbers rather than inventing new ones. |
| `agent/week2_latency_observer.py` | 82-191 | Opt-in (`NXLYR_LATENCY_CSV`). Uses Pipecat's `UserBotLatencyObserver`. |
| Pipecat 1.5.0 `transports/websocket/fastapi.py` | 299-325 | `on_client_connected` fires inside the input transport's `start()`, on the pipeline's StartFrame. That is when the greeting is queued, so everything in `run_bot` before the pipeline starts is **outside** the pipeline's own clock. |
| Pipecat `observers/user_bot_latency_observer.py` | 230-246, 278-289 | `on_first_bot_speech_latency` is measured from `ClientConnectedFrame`, not from pickup. And **a `VADUserStartedSpeakingFrame` before the first bot speech sets `_first_bot_speech_measured = True` (line 244), abandoning the measurement.** So when the caller speaks first, Pipecat records no greeting latency at all. This is one reason the existing logs cannot explain the two cases. |
| Pipecat `transports/base_output.py` | 664-682 | `BotStartedSpeakingFrame` is created when the output transport starts sending bot audio, so it is the right frame for "first audio sent". |
| Pipecat `audio/vad/silero.py`, `audio/turn/smart_turn/local_smart_turn_v3.py` | 33-60, 137-172; 35-78 | Model files are 2.3 MB and 8.7 MB. `SileroOnnxModel` keeps **recurrent state on the instance** (`reset_states`), so one analyzer object must not be shared between two live calls. Only the underlying ONNX session could be shared. |
| Existing tests | `test_turn_release.py`, `test_prompt.py:447`, `test_ws_auth.py`, `test_kb_loader.py`, `test_log_hygiene.py` | Style: `unittest`, `IsolatedAsyncioTestCase`, `patch.object(server, "run_bot", AsyncMock())`. `test_prompt.py:447` asserts `lead_source` is not a `run_bot` parameter, so a new keyword argument is fine as long as it has another name. |

**One measurement I ran** (read-only, on the founder's Mac, in `agent/venv`, nothing written): constructing `SileroVADAnalyzer()` took 58, 27, 27 ms and `LocalSmartTurnAnalyzerV3()` 25, 20, 20 ms; the one-time import was 533 ms. So the per-call model load is about **50 to 85 ms here**. That is not the missing 3 seconds. The VPS CPU is slower; its figure is UNVERIFIED and is what the new `models=` field will show.

**Not verified:**

- Any timing on the VPS (no SSH, by rule). Every VPS figure in this spec is UNVERIFIED until the exit test.
- How long the Supabase fetch, the Redis connect, the Deepgram WebSocket connect and the first ElevenLabs TLS connect take on the VPS.
- What Exotel does between pickup and the `connected`/`start` messages. UNVERIFIED whether Exotel's call detail records give an answer timestamp.
- Whether nginx adds delay to the WebSocket upgrade. UNVERIFIED.
- The historical pre-change 300 s KB cache-expiry hit rate during the founder's earlier test calls (no call-time record exists). The implemented call path no longer expires cached entries.
- `test_kb_loader` still fails five tests on main (F23; `AGENTS.md` Commands). I did not run it. This task fixes them (test-only, see Files touched and T13).

## Why silence may be slower

The server does the same work before the first greeting audio whether the caller speaks or not: nothing in `server.py:675-745` or `bot.py:299-500` reads caller audio, and the greeting is queued on pipeline start, not on speech. So a 3 s difference cannot come from server work **unless something else differs between the two groups of calls**. Four candidates:

| # | Hypothesis | Reasoning | What settles it |
| --- | --- | --- | --- |
| H1 | **Speak-first measures a different event.** The caller's "hello" trips VAD, and `VADUserStartedSpeakingFrame` starts an interruption (`bot.py:208`, `enable_interruptions=True`), which can cancel the greeting still being generated or played. The 2.5 to 3 s the stopwatch shows would then be the reply to "hello" (about 1 s of speech plus the 1.4 s median turn in the baseline), not the greeting. | Fits the Pipecat observer dropping the measurement when the user speaks first (line 244) and the founder's "no second greeting". It is an inference from documents, not an observation. | New line `caller_spoke_before_greeting_audio`. If it appears on speak-first calls and `first_bot_audio_sent` does not, or comes late, H1 is true. The recording on the phone (or the stopwatch note "heard greeting? y/n") confirms it. |
| H2 | **The missing seconds are outside our server.** Silent calls show the same server-side pickup-to-first-audio as speak-first calls, but the stopwatch reads about 3 s more. The gap is before the WebSocket connects (Exotel bridging, the applet fetch, nginx), or after the audio leaves (Exotel buffering), or in when the stopwatch was started. | The only remaining place for a difference, if the two server-side numbers match. | Compare `ws_connected` to `first_bot_audio_sent` per call against the stopwatch. Stopwatch minus server-side number = the part we cannot see, reported per call. |
| H3 | **The former KB-expiry confound is designed out.** The call path serves any cached KB regardless of age and never fetches because an entry crossed the 300 s stale threshold. Only the 240 s background refresh fetches during normal operation; an empty cache after a failed preload falls through to a worker-thread fetch. | `kb_source` should therefore be `cache` on every call after a successful preload or first successful miss, including when that entry is stale. Idle gaps can still expose other cold effects. | If any call shows `kb_source=fetch`, no KB was cached when that call began. Read staleness from the separate `Serving stale KB cache_age_seconds=...` WARNING, not from `setup_done`. The exit test still records idle gaps and alternates order so silence and other cold effects are not confounded. |
| H4 | **Cold start-up cost is spread across several steps** (new TLS connection to ElevenLabs on the per-call session at `bot.py:399`, DNS, ONNX cold read, Deepgram connect). It explains the 13-idle-hour call (TTS first audio 1,582 ms against 160 ms) but not a difference between silent and speaking callers. | The greeting TTS time is measured by Pipecat and was 1,582 ms on that one call, so the delay is inside the TTS call, not before it. | Existing `ElevenLabsHttpTTSService TTFB` line (needs `NXLYR_LATENCY_CSV`) plus the new `t_ms` of `first_bot_audio_sent`. A call-0 after container restart is part of the exit test. |

I do not claim which is true. The test matrix is designed so each outcome points at exactly one of them.

## Design (files to touch and why)

Three parts. Part 1 is certain. Part 2 is certain and small. Part 3 is conditional on the numbers Part 1 produces, and is a follow-up task, not part of this PR (see its first bullet).

### Part 1 — log lines (the visibility)

One format, one prefix, so a single `grep 'call timing'` reads a whole call:

```
call timing: <event> conn=<6 hex> t_ms=<int since ws_connected> [key=value ...]
```

`conn` is a random 6-hex-digit id made at `accept()`. It is **not** the Exotel `call_sid` (not known until the handshake is read) and is not derived from any phone number, name or secret. Values are integers, enums (`cache`, `fetch`) or event names. No phone, name, URL, SID or token goes in any field.

Events, in order (`models_built` lands wherever the build finishes; the others are as listed):

| Event | Where | Extra fields |
| --- | --- | --- |
| `ws_connected` | `server.py` `websocket_endpoint`, immediately after `await websocket.accept()` (678) | none. `t_ms=0` by definition. This is the pickup proxy. |
| `models_built` | `bot.py` `run_bot`, right after the aggregator params are built off the loop (431) | `models_ms`: the time to construct the VAD and Smart Turn analyzers on this call. A per-call line of its own (founder, r2), so the VPS figure for the 150 ms decision is one grep away. |
| `setup_done` | `bot.py` `run_bot`, just before `worker` is created (about 471) | `kb_ms`, `kb_source=cache\|fetch`, `redis_ms`, `handshake_ms` (time from `ws_connected` to entering `run_bot`, which covers the Redis admission steps). |
| `greeting_queued` | `bot.py` `on_client_connected`, just before `worker.queue_frames` (498) | none |
| `first_bot_audio_sent` | a small observer added to the `observers` list at `bot.py:449`, first `BotStartedSpeakingFrame` only | none |
| `caller_spoke_before_greeting_audio` | the same observer, a `VADUserStartedSpeakingFrame` seen before the first `BotStartedSpeakingFrame` | none. Fires once. **This is a fourth line beyond the three first asked for, approved by the founder in r2; it is what separates H1 from H2.** No personal data in it. |

To carry the start time: `server.py` takes `time.monotonic()` after `accept()` and passes it, plus `conn`, to `run_bot` as two new optional keyword arguments (`ws_connected_at`, `conn_id`), defaulting to `None` so every existing caller and test still works. The observer and `on_client_connected` read them from the closure inside `run_bot`.

This is deliberately **not** another use of `UserBotLatencyObserver`: its first-speech event measures from the pipeline start and is dropped when the caller speaks first (see table above).

### Part 2 — stop blocking the event loop, bound every wait (F06, F12 on the pickup path)

1. **Preload the KB at server start, refresh in the background.** In `lifespan` (`server.py:82-107`): `await asyncio.to_thread(load_kb, KB_PROJECT_SLUG)` before `yield`, then start one background task that every 240 s refreshes the cache through `asyncio.to_thread`, and is cancelled on shutdown. **Only that background task fetches during normal operation.** The call path serves whatever is cached regardless of age and never fetches on a cache hit. On every failed refresh it keeps serving the last good KB and logs a WARNING with the age of the cached KB in seconds (founder, r2); the message carries no secret, URL or KB content (the exception text is reduced to its class name, because `requests` errors can embed the Supabase URL). A failed first load at startup logs an error and **must not crash the server** (health checks must not depend on Supabase); with nothing cached, the first call falls through to a worker-thread fetch.
   - `kb_loader.py` gets `refresh_kb(slug)`, which always fetches and stores. `load_kb` serves any cached entry, including a stale one, and fetches only when the cache is empty. `_fetch_kb` stays synchronous so `prompt_harness.py` (sync) keeps working.
2. **Call path never blocks the loop.** `bot.py:337` becomes `await asyncio.to_thread(load_project_kb)`. With a warm cache this returns in microseconds; on a cold or failed preload it runs the fetch in a worker thread so other calls keep their audio.
3. **Models off the loop.** `bot.py:431` builds the aggregator params via `asyncio.to_thread(_build_user_aggregator_params)`. Same per-call objects as today (so no shared VAD state, no behavior change), only constructed off the event loop. Cost on this Mac: about 50 to 85 ms; this stops that cost stalling other calls.
4. **Short, operation-specific timeouts, using the house numbers:**
   - `kb_loader._fetch_kb` `requests.get(..., timeout=10)` becomes `timeout=(2.0, 5.0)` (connect, read). 5.0 matches `demo_guard.SUPABASE_TIMEOUT_SECONDS`. The old single 10 s is the longest silent wait a caller can hit.
   - `tools.make_redis_client` (498-529): `from_url(..., socket_connect_timeout=1.0, socket_timeout=2.0)` and `await asyncio.wait_for(client.ping(), 1.0)`. Matches `ws_auth` (1.0) and `demo_guard` (2.0). The socket timeout also bounds `hset`/`expire` in `_set_session_flag` (148, 152) without editing those lines, which 008 will rewrite.
   - `server.get_demo_redis_client` (291-322): same two socket timeouts on `from_url`, so a Redis that accepts the connection and then stalls cannot hang the `/ws` or `/demo/call` path beyond the existing `wait_for` caps.
   - A timeout on the Redis client in `run_bot` still degrades to `None` (current, deliberate behavior at `bot.py:463-467`); it must not abort the call.

### Part 3 — conditional, only if Part 1's numbers call for it

Decided after the first instrumented calls, not before:

- **Share the ONNX sessions across calls** (only the `InferenceSession`, never the analyzer object, because of per-instance VAD state). Needs a subclass or patch around Pipecat internals (UNVERIFIED stable across Pipecat versions). Do it only if `models_ms` on the VPS is over 150 ms; otherwise Part 2.3 is enough. **Founder, r2: this task ships the `models_built` line only. The VPS figure exists only after deploy, which is after this PR, so preload is a follow-up task unless the number is already known before merge.**
- **Run the independent set-up steps concurrently** (`asyncio.gather` over KB, models, Redis). Only if `kb_ms + models_ms + redis_ms` is still over 300 ms with a warm KB.
- **Warm the ElevenLabs connection** (the TLS connect on the per-call session, `bot.py:399`). Only if H4 shows a cold-call greeting TTS well above 500 ms on a warm process. A boot-time warm-up costs one request and must not change model or voice.

### Files touched

| File | Why | Overlap |
| --- | --- | --- |
| `agent/server.py` | `lifespan` preload and refresh task; `ws_connected` log and the two new `run_bot` arguments in `websocket_endpoint`; Redis socket timeouts in `get_demo_redis_client` | **012** also edits `server.py` and `run_bot`. Hunks are separate (lifespan 82-107, `/ws` 675-745, 291-322). Whoever merges second rebases. |
| `agent/bot.py` | timing marks and observer in `run_bot` (about 305-500); `to_thread` for KB (337) and aggregator params (431); two optional keyword args | **012** edits `run_bot` too. Keep my edits as single-line wraps and one small observer function placed above `run_bot`, to keep conflicts small. |
| `agent/kb_loader.py` | tuple timeout; `refresh_kb` | none |
| `agent/tools.py` | `make_redis_client` only (498-529) | **008** edits `tools.py`. I touch only that function; 008's `_set_session_flag` and tool handlers are untouched. |
| `agent/test_startup_timing.py` (new) | tests below | none |
| `agent/test_kb_loader.py` | fix the five F23 errors, test-only: `setUp` clears `kb_loader._kb_cache` instead of calling the non-existent `load_kb.cache_clear`; adjusted for the new refresh function (founder, r2) | none |
| `docs/memory/inbox/` | one note with the exit-test result | none |

Not touched: `prompt.py`, `log_scrub.py`, `ws_auth.py`, `demo_guard.py`, `Dockerfile`, `requirements.txt`, nginx, workflows.

## Data touched

- **Supabase, read only, no SQL written or run:** table `projects` (columns `id`, `name`, `config`) joined to `tenants` (column `slug` only, in the filter). It is the same REST GET `kb_loader._fetch_kb` already makes (`kb_loader.py:57-72`). Change in volume: one background read every 240 s while the server is up (about 360 per day), plus a call-path read only when nothing is cached. A cached entry never triggers a call-path read because of age. Never `SELECT *` on `tenants`; the query selects `tenants!inner(slug)` and nothing else from that table.
- **Redis, behavior unchanged:** the `/ws` admission keys (`getdel` of the binding key, `ws_auth.py:203-204`) and the per-call session hash (`CallResources.session_key`, `tools.py:99`; fields written by `_set_session_flag`, `tools.py:148,152`). Only the client's connect and socket timeouts change.
- **No tables, columns or migrations are added or altered.**
- **Logs:** new `call timing:` lines contain integers, `cache`/`fetch`, a random `conn` id. No phone, name, secret, URL or SID.

## Acceptance tests (automated)

New file `agent/test_startup_timing.py` plus the regression set. Command (from the worktree root):

```
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_startup_timing agent.test_kb_loader agent.test_turn_release agent.test_prompt agent.test_ws_auth agent.test_log_hygiene agent.test_demo_guard
(cd agent && "$PY" -c "import server, week2_latency_observer")
```

| # | Test | Proves |
| --- | --- | --- |
| T1 | Run `lifespan` with `requests.get` patched: it is called once before the first request is served, and a following `load_kb()` makes no HTTP call. | KB is preloaded at start (F06). |
| T2 | Background refresh with a patched clock: after the interval a second fetch happens and the cache holds the new value; when the second fetch raises, the old value is still returned and a WARNING is logged on that refresh and on each further failed refresh, containing the cache age in seconds and none of the exception text, URL or KB content; if the very first preload raises, `lifespan` still yields and the app starts; shutting the app down cancels the task with no pending-task warning. | Refresh works, fails safe, never crashes startup, and cleans up. |
| T3 | Patch `requests.get` to sleep 0.5 s. Start a task that increments a counter every 10 ms, then `await` the call-path KB load with a cold cache. The counter must advance at least 30 times during the fetch. | The fetch no longer blocks the event loop (F06, the exact bug). Fails on current main. |
| T4 | Same ticker, patch `SileroVADAnalyzer` and `LocalSmartTurnAnalyzerV3` to sleep 0.2 s: the counter keeps advancing while `run_bot`'s aggregator params build. | Model construction is off the loop. |
| T4b | `run_bot`'s aggregator-params step logs exactly one `call timing: models_built conn=XXXXXX t_ms=<int> models_ms=<int>` line per call. | The per-call model-construction line exists. |
| T5 | `kb_loader._fetch_kb` calls `requests.get` with `timeout=(2.0, 5.0)`. | KB timeout is short and split (F12). |
| T6 | `make_redis_client`: patch `redis.asyncio.from_url` to capture kwargs (`socket_connect_timeout=1.0`, `socket_timeout=2.0`) and return a client whose `ping` sleeps 10 s. It returns `None` in under 1.5 s and logs an error with no exception escaping. Same kwargs check for `get_demo_redis_client`. | Redis cannot hang the pickup path (F12) and still degrades to `None`, not a dropped call. |
| T7 | Drive `/ws` with a fake WebSocket and a patched `run_bot`: exactly one `call timing: ws_connected conn=XXXXXX t_ms=0` line is logged before `run_bot` is awaited, and `run_bot` receives `ws_connected_at` and `conn_id`. Existing `test_ws_auth` cases pass unchanged. | The pickup line exists and the plumbing works. |
| T8 | Feed the timing observer frames: `ClientConnectedFrame`, then `BotStartedSpeakingFrame`, then another `BotStartedSpeakingFrame`. Exactly one `first_bot_audio_sent`. | One first-audio line per call. |
| T9 | Observer, caller speaks first: `VADUserStartedSpeakingFrame` then `BotStartedSpeakingFrame`. Exactly one `caller_spoke_before_greeting_audio`, then the first-audio line. Caller silent: no `caller_spoke...` line. | Both cases are distinguishable in the log (H1). |
| T10 | Every `call timing:` line captured in T7-T9 matches `^call timing: [a-z_]+ conn=[0-9a-f]{6} t_ms=\d+( [a-z_]+=[a-z0-9]+)*$`, and contains no run of 7 or more digits, `@`, `://` or `Bearer`. Run the captured text through `log_scrub.scrub`: output equals input. | No phone, name or secret can enter these lines; the 004 scrubber has nothing to remove. |
| T13 | `agent.test_kb_loader` passes in full (the five F23 errors are gone), including a case for the cache behavior the task changes (hit regardless of age, miss, forced refresh). | F23 fixed, test-only. |
| T12 | Regression: `test_turn_release`, `test_prompt` (including the `run_bot` signature test at 447), `test_ws_auth`, `test_log_hygiene`, `test_demo_guard` all pass; import smoke passes. | Nothing else moved. |

I expect T3 to fail on current main and pass after the change; the builder shows that.

## Exit test (what I do by hand on real calls, with exact commands)

Tags: 🧑 YOU does it, 👀 VERIFY you check it. The agent does not SSH.

Files used: baseline `/Users/vansh/Desktop/SALES AGENT/baseline-2026-10-22/`, 011 exit `/Users/vansh/Desktop/SALES AGENT/exit-011-2026-10-23/`, scripts in `/Users/vansh/Desktop/SALES AGENT/tools/`. Run every step in one terminal tab so `T0` survives.

**What one "call" is.** You place a demo call from your own phone. A stopwatch (a second device) starts when you press answer and stops at the first word you hear from the bot. Two kinds:

- **S** (caller speaks first): you say "hello" at once, as soon as you answer. Stop the watch at the first bot word you hear, and note whether that word was the greeting or an answer to your "hello" (y/n: "did I hear the greeting?").
- **W** (caller waits): you say nothing until the bot speaks. Stop at its first word.

**Order, to unconfound silence from idleness.** Three blocks. Before each block, leave the system idle for at least 6 minutes to expose non-KB cold effects. The KB call path does not expire cached entries; the 240 s background refresh is the only normal fetch. Within a block, place the two calls back to back (about 30 s apart). Alternate which kind goes first:

| Block | Idle before | First call | Second call |
| --- | --- | --- | --- |
| 1 | 6+ min | W | S |
| 2 | 6+ min | S | W |
| 3 (only if needed) | 6+ min | W | S |

Write down, per call: kind, idle minutes before it, stopwatch seconds, heard-greeting y/n.

**Minimal exit test (founder, r2), in this order:** call 0, then block 1, then block 2. That is 5 calls on the new build (and 4 on today's build for "before"). **Block 3 is run only if those calls do not settle the four hypotheses.** The decision to run block 3 is made after reading the timing lines from call 0 and blocks 1 and 2, before restoring the demo limits.

### A. Before (today's build, no deploy yet)

1. 🧑 Raise the demo limits (same as the baseline):
   ```
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET demo:config phone_limit 100 ip_limit 100 phone_cooldown_seconds 5 ip_cooldown_seconds 5"
   ```
2. 🧑 `T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$T0"`
3. 🧑 Place blocks 1 and 2 (4 calls). Save the notes as `before-notes.md`.
4. 🧑 Restore the limits (both reads empty):
   ```
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL demo:config"
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL demo:config"
   ssh nxlyr-vps "docker exec nxlyr_redis redis-cli GET demo:kill"
   ```

"Before" has no `call timing` lines (they do not exist yet). Its numbers are the stopwatch table from step 3 (4 calls), set beside the earlier numbers in the baseline and 011 exit reports.

### B. After (the merged build)

5. 🧑 Merge is the human's. Before the deploy, copy the container's latency files off (they are lost on deploy), as in the baseline report step 4. 👀 Confirm the container is healthy twice, a few seconds apart.
6. 🧑 Call 0, **process-cold**: the first call after the deploy, no warm-up call, kind W. Note the stopwatch time.
7. 🧑 Repeat steps 1 to 4 for the new build: blocks 1 and 2 (call 0 above is already placed), with `after-notes.md`. Run block 3 only if the minimal set does not settle H1 to H4.
8. 🧑 Pull only the timing lines and the existing latency files, and check them for phone numbers (both counts must be 0):
   ```
   ssh nxlyr-vps "docker logs nxlyr_agent --since $T0 2>&1 | grep 'call timing'" > after-timing.log
   grep -cE '[0-9]{7,}' after-timing.log
   ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call.csv /tmp/ && docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/"
   scp nxlyr-vps:/tmp/section6_real_call_events.log ./events.log
   grep -cE '[0-9]{10}' ./events.log
   ssh nxlyr-vps "rm -f /tmp/section6_real_call.csv /tmp/section6_real_call_events.log"
   ```
9. 🧑 Log-leak counts (it asks for the last 6 digits of your test phone; run it on its own line):
   ```
   /Users/vansh/Desktop/SALES\ AGENT/tools/leak_counts.sh "$T0"
   ```
   👀 Every leak gate reads 0 and `masked` is not negative.
10. 🧑 Report with the latency script (after a fresh deploy use `--from-call 0`):
    ```
    python3 /Users/vansh/Desktop/SALES\ AGENT/tools/latency_report.py ./events.log --from-call 0 --md
    ```
11. 🧑 Save everything as `/Users/vansh/Desktop/SALES AGENT/exit-015-<date>/` (notes files, `after-timing.log`, `events.log`).

### What I compare

| Measure | Before (known) | After (to fill in) | Pass |
| --- | --- | --- | --- |
| **Server side `ws_connected` to `first_bot_audio_sent` (new)** | no data | per call, p50 and max | **GATE: 1.5 s or less on the VPS, every W and S call and call 0** |
| Greeting by stopwatch, caller waits (W) | about 6 s (011 exit note); baseline 3.0 to 4.9 s | each W call (2 in the minimal run), plus call 0 | reported; under 2.0 s is the hoped-for figure, not the gate |
| Greeting by stopwatch, caller speaks first (S) | 2.5 to 3 s (011 exit note) | each S call (2 in the minimal run) | reported, with the y/n note on whether it was the greeting |
| **Gap = stopwatch minus server side (new)** | no data | per call | **reported on every call.** Over 1.5 s is an Exotel / VPS-region item for a separate task, not an L1 failure |
| `kb_source` on every `setup_done` | n/a | all `cache` after a successful preload or first successful miss | all `cache`; a stale entry also reports `cache`, so read staleness from the separate WARNING line |
| `kb_ms`, `redis_ms`, `models_ms` (new) | no data | per call | reported; `models_ms` over 150 ms on the VPS opens the preload follow-up |
| Call 0 (process-cold), greeting TTS first audio | 1,582 ms (011 exit call 1) | from `events.log` | under 500 ms (provisional, founder r2; tightened after data) |
| Existing gates | 011 exit: 0 of 92 stalls, p95 2,428 ms | from `latency_report.py` | no worse than 011 exit; 004 leak gates 0 |
| Caller-speaks-first calls: lines present | n/a | `caller_spoke_before_greeting_audio` appears only on S calls | settles H1 |

**How the result is read** (so the outcome decides what we say, not the other way round):

- Server side at or under 1.5 s on W calls and the stopwatch still near 6 s: the gap is outside our process (H2). L1 passes on its gate. We report the gap per call; closing it is a separate Exotel / VPS-region item, not code in this task.
- Server side at or under 1.5 s on W and S, stopwatch fast on both: fixed. The `kb_source`/`kb_ms` fields show what the preload bought.
- `caller_spoke_before_greeting_audio` on S calls with a late or missing greeting line: H1 is true; the 2.5 to 3 s was the reply to "hello". Whether speak-first should interrupt the greeting is a product decision for the founder, not made here.
- Any `kb_source=fetch` means the cache was empty when that call began, normally because preload failed; it is not age expiry. If idle blocks are slow while `kb_source=cache`, investigate H4 and Part 3. A stale cached entry still reports `cache`; its age appears only in the separate WARNING.

## Risks and rollback

| Risk | Likelihood | Effect | Mitigation |
| --- | --- | --- | --- |
| Supabase is down at server start | low | Preload fails | Logged as an error; server starts; first call falls back to a fetch in a thread (no loop block). Same as today's behavior for the call, better for the other calls. |
| Refresh serves a stale KB if Supabase stays down | low | KB edits not picked up | Decided (founder, r2): last good KB is served indefinitely; a WARNING with the cache age is logged on every failed refresh. No maximum stale age. |
| A KB edit takes up to one interval to show | certain | None | The background refresh interval is 240 s. Calls keep serving the last good entry if a refresh fails. |
| Redis socket timeout of 2 s turns a slow Redis into `None` mid-call | low | Session flags for drop classification are not written for that call | Existing, deliberate degradation (`bot.py:463-467`); the call is not dropped. T6 asserts it. |
| Edits collide with 012 and 008 | likely | Merge conflicts | Small hunks, listed in "Files touched". Merge 015 first or rebase after; tools.py is only `make_redis_client`. |
| New observer adds per-frame cost | very low | A few microseconds per frame | It checks two frame types and does nothing else. |
| `asyncio.to_thread` and the default thread pool under load | low | Queued thread work | One background KB fetch per 240 s, an additional call-path fetch only when the cache is empty, and one model build per call; the pool has dozens of workers by default. |
| Log lines leak data | very low | Policy breach (004) | Fixed format, integers and enums only, `conn` random; T10 and the exit leak counts. |
| The 2 s stopwatch figure is not reachable in our code | real | Stopwatch goal missed | The gate is server side (1.5 s). If the gap is over 1.5 s, it is reported as an Exotel / VPS-region item for a separate task, not an L1 failure. |

**Rollback:** the change is one PR. Merge = deploy, so rollback is reverting the merge commit on `main` and letting `deploy.yml` redeploy (🧑, `git pull` and `docker compose up -d --build` together, per CONSTRAINTS rule 2). No data, schema or config migration to undo. The new log lines are INFO and harmless if left in. If only the preload misbehaves in production, an empty cache still falls through to a worker-thread fetch; after any successful load, calls keep serving that cached entry regardless of age, so a partial rollback is not needed.

## Open questions for me

All eight questions from r1 are answered by the founder; none remain. Recorded here so the spec is self-contained:

1. **Target.** The gate is server side: WebSocket connect to first greeting audio sent is 1.5 s or less on the VPS. Stopwatch and gap are reported on every call. A gap over 1.5 s is an Exotel / VPS-region question for a separate item, not an L1 failure.
2. **Stale KB.** Keep serving the last good KB if a refresh fails; log a WARNING on every failed refresh with the cache age (no secrets, no KB content). A failed first load at startup does not crash the server.
3. **`test_kb_loader` (F23).** Fix, test-only, in this task.
4. **Fourth log line.** `caller_spoke_before_greeting_audio` is added; no personal data in it.
5. **Cold-call TTS.** 500 ms provisional for first greeting TTS audio on a cold first call; tightened after data.
6. **Rest of F12.** Exotel dial, contact insert and Telegram timeouts get their own task, not this one.
7. **Model preload.** Add a per-call `models_built` line; preload only if the VPS figure is over 150 ms. That figure exists only after deploy, so preload is a follow-up unless the number is known before merge.
8. **Exit test size.** Minimal: call 0, then block 1, then block 2. Block 3 only if those do not settle H1 to H4. The order is stated in the Exit test section.
