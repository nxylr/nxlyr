---
name: Task spec
title: "004: Log hygiene (audit F09)"
labels: task, audit
---

Status: APPROVED r3 (founder)
Drafted as r1 by the lead on 2026-10-22; the founder's answers to the r1 open questions are recorded in r2 (see "Open questions for me", now answered). Implementation exists, uncommitted, in this worktree (`.agent/reports/builder-1.md`, `.agent/reports/review-1.md`).
Docs corrections after review 1 (R6, R8), review 2 (N1, N3) and review 3 (test-table rows for t1c, t7b and the T8 `logger.add` guard), 2026-10-22: exit-test gates and test table only. Scope, design and the founder's decisions are unchanged. Revision r3 approved by the founder after reading the N1/N3 changes and review 3. Worktree `../nxlyr-worktrees/004-f09-log-hygiene`, branch `task/004-f09-log-hygiene`, from `origin/main` 1e47490.
Depends on: 003 (merged). Edits the same file as 006 (`server.py`): this task touches 3 lines there, see Risks.
Builder: Codex (default). Reviewer: Claude (must differ from the builder).

## Goal

After this task, the agent container's logs contain no secrets or credentials, no full phone numbers (only `****` + last 4 digits), no Redis URLs, and no prompt or knowledge-base text. Behaviour is unchanged: only what is logged changes.

## Non-goals

- Any behaviour change. Responses, status codes, retries, rate limits, tool results are untouched.
- `demo_guard.py` logic. Its one log call (line 147) is static and stays.
- Authenticating or removing `/start`; `/start` and `trigger_exotel_call` still return the raw Exotel body **to the HTTP caller** (`server.py:246-253`, `"detail": res_data or resp_text`). That is a response, not a log. Both facts ("`/start` returns the raw Exotel body to the HTTP caller" and "`/start` is unauthenticated") go on the queue in the close-out docs PR, **not in this task** (founder, r2). What nginx does with `/start` is recorded read-only in section 3 below.
- Log rotation. `docker-compose.yml` has no `logging:` key on any service (checked in the repo copy), so Docker's default `json-file` driver applies with no size limit and logs can fill the disk. Whether the VPS has a global limit in `/etc/docker/daemon.json` is **UNVERIFIED**. New queue item for later, **not this task** (founder, r2).
- The other items bundled under "hygiene batch (004)" in `hot.md` (`WS_AUTH_MODE` default, VPS reboot, `new-task.sh` footgun, branch protection, F23). Not in this task.
- nginx access/error logs and Docker daemon logs on the VPS host. This task covers the **container's** output only.
- Dev-only scripts that never ship (all are in `agent/.dockerignore`): `prompt_harness.py`, `mock_exotel_client.py`, `check_dotenv.py`, `test_pipeline.py`, `analyze_week2.py`, `backfill_ttfb.py`, `stt_accuracy_test.py`.
- Rotating credentials or cleaning old logs. **Not planned** (founder, r2): to the founder's knowledge no log excerpt has ever been pasted into a chat, issue, PR or memory file; the founder is verifying this and will say if one is found. No rotation is planned in this task.
- Schema changes. None. No SQL is run.

## Design (files to touch and why)

### 0. What I read

All against the worktree at 1e47490. Line numbers are re-found, not copied from the audit (they happen to be unchanged: `bot.py:96`, `server.py:255`, `server.py:570`).

| Where | What I checked |
|---|---|
| `agent/bot.py:52, 92-96` | the only loguru handler configuration in shipped code |
| `agent/bot.py:128-175, 342-588` (`load_project_kb`, `build_system_prompt`, `run_bot`) | which variables a failing line inside `run_bot` could name; log calls at 364, 378, 562, 567, 588 |
| `agent/server.py:153-262` (`trigger_exotel_call`) | failing-line variables `url`, `data`, `auth`; raw body logged at 243-245; `logger.exception` at 255 |
| `agent/server.py:281-325` (`get_demo_redis_client`) | local `redis_url` at 306 |
| `agent/server.py:360-419` (`store_contact_submission`, `notify_contact_submission_via_telegram`) | failing-line variables `endpoint`, `headers`, `payload` (Telegram: `endpoint` holds the bot token, see E3) |
| `agent/server.py:440-580` (`request_demo_call`) | every log call; 449/496/540/544/559 already log only `type(error).__name__` (task 003) |
| `agent/server.py:600-640, 675-775` (`/contact`, `websocket_endpoint`) | log calls at 621, 683-772 |
| `agent/tools.py:125-160, 205-245, 285-310, 380-435, 480-514` (`_set_session_flag`, `book_site_visit`, `transfer_to_human`, `end_call`, `make_redis_client`) | every log call; `redis_url` logged at 507 and 510 |
| `agent/ws_auth.py:154-156` (`format_call_sid`) | `repr(call_sid)[:64]`; `ws_auth.py` has no log calls of its own |
| `agent/demo_guard.py:130-152` (`read_config`) | single log call, static field name |
| `agent/kb_loader.py:44-93` (`_fetch_kb`) | no log calls, but exception text embeds `response.text` (non-200 only) and the slug |
| `agent/week2_latency_observer.py:120-145` | one `print` of latency numbers; runs only when `NXLYR_LATENCY_CSV` is set |
| `agent/test_demo_guard.py:339-342, 573-604` | how tests import `server`; existing `test_failure_logs_exclude_phone_and_ip` (a `diagnose=True` sink) |
| `agent/Dockerfile` (CMD, ENV), `agent/.dockerignore`, `docker-compose.yml` | uvicorn runs with defaults; no `logging:` options in compose; `COPY *.py` ships any new module; tests must be listed in `.dockerignore` |
| pipecat-ai 1.5.0 in the main checkout venv: `runner/utils.py:180-276`, `services/openai/base_llm.py:232, 296-312`, `adapters/services/open_ai_adapter.py:182-196`, `services/tts_service.py:137, 734`, `services/elevenlabs/tts.py:990, 1362`, `services/llm_service.py:248-252` | what the library itself logs at DEBUG |

### 1. Inventory of every logger call and print in `agent/*.py`

Decisions: **keep** = no change; **mask** = still logged, phone/secret patterns removed by the new scrubber; **remove** = the sensitive part is taken out at the source or by config. **Tracebacks.** A `logger.exception` call renders a traceback. With loguru's default `diagnose=True`, each frame is annotated with the values of the variables that appear **on that frame's failing source line**. It does **not** print every local (checked in review with a toy example: a secret named on the failing line was printed, a secret local not named on it was not). Section 1b says, row by row, which variables a failing line names and whether a leak was demonstrated or only read from the code.

**What is proven, in one place** (corrected after review 1, R8):

- **Pipecat's own DEBUG line `pipecat/runner/utils.py:276`** prints the parsed Exotel handshake, including the **full `from` and `to` phone numbers**, once per call. Proven: pipecat's real `parse_telephony_websocket` was run on a fake Exotel `start` message through an old-style default handler (full numbers printed) and through the new handler (`****3210`, `****8901`).
- **Pipecat's own DEBUG line `pipecat/services/openai/base_llm.py:304-306`** prints the whole LLM context, including the **system prompt (which embeds the KB)**, on every LLM call. Proven the same way, with pipecat's real `OpenAILLMService.get_chat_completions` and a marker string in the system message.
- **Our own direct log calls.** `tools.py:507` (INFO) interpolates `redis_url` on every call, so a Redis URL, possibly with a password, is logged directly, not through a traceback; this is the `redis://` line seen in the logs. `server.py:243-245` interpolated the raw Exotel response body into a WARNING. Both proven by reading the lines.
- **Production runs `DEBUG`.** `LOG_LEVEL` is unset in the VPS `.env` (founder, r2), so the first two bullets are expected to be live today. Batch A of the exit test is the evidence.
- **Not proven:** that any production traceback has ever printed a secret, a phone number, a prompt or KB text through `diagnose`. Audit F09 reports it for the Exotel call site; E1-E7 below say what is read versus unverified. An earlier draft of this spec said tracebacks print "every local variable in every frame" and that `run_bot` frames put "full prompts and KB text" into the logs. Both statements are withdrawn.
- **The fix does not depend on which tracebacks were real.** `diagnose=False` removes the whole class; the scrubber and the `base_llm` filter cover the proven leaks above.

**1a. loguru configuration and handlers**

| # | File:line | What it does / logs | Decision |
|---|---|---|---|
| C1 | `bot.py:95-96` | `logger.remove()`; `logger.add(sys.stderr, level=LOG_LEVEL or "DEBUG")`. No `diagnose`/`backtrace` argument, so loguru 0.7.3 defaults apply: **`diagnose=True`, `backtrace=True`**. This single handler receives every loguru call in the process, including pipecat's. | **remove the leak**: replace with `configure_logging(level)` from new `log_scrub.py` (see section 2). `diagnose=False`; text passes through `scrub()` before it is written. `backtrace` left at its default (it only adds more frames; with `diagnose=False` frames carry code lines, not values). |
| C2 | `test_pipeline.py:60-61` | its own `logger.remove(0); logger.add(sys.stderr, "DEBUG")`, defaults apply | keep (dev-only, not in image) |
| C3 | `test_demo_guard.py:582` | test sink with `diagnose=True`, on purpose | keep |
| C4 | `Dockerfile` CMD `uvicorn server:app` | uvicorn logs through stdlib `logging`, **not loguru**, so C1 does not cover it. Access lines are `client - "METHOD path HTTP/x" status`. `/demo/call` and `/start` carry the phone in the JSON body, not the URL. Whether Exotel appends a query string to `/ws` is **UNVERIFIED**. | keep; covered only by the exit-test counts |
| C5 | env `LOG_LEVEL` | default `DEBUG` in `bot.py:96`. **Founder, r2:** there is no `LOG_LEVEL` line in the VPS `.env`, and the container check showed it empty. So production runs the code default `DEBUG`, and the pipecat prompt line (P2) and `from`/`to` line (P1) are expected to be live today; Batch A of the exit test is the evidence. Note: I confirmed that a variable that is *set but empty* would crash the agent at import (`os.getenv("LOG_LEVEL", "DEBUG")` returns `""`; loguru raises `ValueError: Level '' does not exist`). Since the agent runs, the variable is unset, not empty. | default stays `DEBUG` (founder, r2). `configure_logging` treats an empty or missing value as `DEBUG`, so both cases are safe. |

**1b. Where `diagnose=True` could put a value in a traceback**

Status key: **Audit** = reported by audit F09 and consistent with the code, not reproduced by me. **Read** = established by reading the failing line, not run. **UNVERIFIED** = not established. **Nothing in this table is a demonstrated production leak**; the demonstrated leaks are in the list above and in section 1d.

| # | Where | Variables named on the failing source line (by reading) | Status | Fixed by |
|---|---|---|---|---|
| E1 | `server.py:255` `trigger_exotel_call` | The failing statement is `async with session.post(url, data=data, auth=auth) as resp:`. It names `url`, `data` (`From` = the dialled phone) and `auth` (`aiohttp.BasicAuth`, whose repr includes login and password, i.e. the Exotel key and token). `api_key`, `api_token`, `phone_number` and `caller_id` are not on that line and could only show through `auth` and `data`. The exit test greps for the *value* (`BasicAuth`), not a label: see the note under the count block. | **Audit; Read.** Not reproduced: UNVERIFIED. | C1 |
| E2 | `server.py:382` `store_contact_submission` | `async with session.post(endpoint, headers=headers, json=payload) as response:` names `endpoint`, `headers` (`apikey` and `Authorization: Bearer` = the Supabase **service-role** key) and `payload` (name, email). Not in the audit list. | **Read.** UNVERIFIED. | C1 |
| E3 | `server.py:418` `notify_contact_submission_via_telegram` | The failing statement `async with session.post(endpoint, json={...}) as response:` spans several lines, and `endpoint` holds the bot token. Whether loguru annotates `endpoint` depends on which source line the traceback records. **Not reproduced:** in review 1's mutation run (`diagnose=True`, scrubber on) a fake bot token that matches no scrubber pattern did **not** appear in the output when the failure was raised at `session.post`. Other failure points were not examined. | UNVERIFIED (weak evidence against a leak at this failure point). | C1; env-value scrub if `TELEGRAM_BOT_TOKEN` is set |
| E4 | `server.py:570` binding failure after a placed call | The failing line in `request_demo_call` is `await issue_binding(await get_demo_redis_client(request), call_sid)`. It names `request` and `call_sid`; it does **not** name `phone_number` or `body`. **The audit's "prints a phone number" at this site is not supported by my reading.** Callee frames (`issue_binding`, `get_demo_redis_client`) add their own failing-line variables; `redis_url` only if the `from_url(redis_url, ...)` line itself raises. | **Read**; audit claim not supported. UNVERIFIED. | C1 |
| E5 | `server.py:621` `/contact` rate-limit failure | The failing line `limited_by = await check_contact_rate_limits(request, email)` names `request` and `email` (the visitor's email: personal data). Callee frames add their own. An earlier draft called this a likely source of the `redis://` line; that is withdrawn (the known source is `tools.py:507`). | **Read.** UNVERIFIED. | C1 |
| E6 | `server.py:750` `Call ended with an error` | The failing line `await run_bot(replay_websocket)` names `run_bot` and `replay_websocket`. Frames inside `run_bot` add whatever their own failing line names. `project_kb` or the system prompt would appear only if that line itself names them (for example if `build_system_prompt(project_kb=project_kb)`, `bot.py:462`, raised). **Possible, not demonstrated.** | UNVERIFIED. | C1 |
| E7 | exception **messages** (survive `diagnose=False`) | `kb_loader.py:~63-70`: Supabase error body (`response.text`) and `requests` error text, logged by `bot.py:378` via `{e}`; `tools.py:154, 510`: redis-py error text via `{e}`; aiohttp `ClientResponseError`/`ContentTypeError` text can contain the request URL, which for Telegram contains the bot token. redis-py's bad-scheme error contains the literal text `redis://` (`redis/connection.py:1262`), which would trip the exit-test grep even though it is not a secret. | The redis-py literal: **Read** in source. The rest: UNVERIFIED at runtime. | scrubber (section 2) |

**1c. Every `logger.*` / `print` in the shipped modules**

| File:line | What is logged | Decision |
|---|---|---|
| `bot.py:364` | `stream_sid`, `call_sid` | keep |
| `bot.py:378` | slug, `call_sid`, `{e}` of KB load failure (E7) | mask (scrubber) |
| `bot.py:562, 567, 588` | `call_sid` | keep |
| `demo_guard.py:147` | invalid `demo:config` field name | keep |
| `server.py:89, 94, 101, 105` | static lifecycle / "Telegram notifications disabled" | keep |
| `server.py:197` | **names** of missing Exotel env vars, never values | keep |
| `server.py:233` | Exotel `CallSid` | keep |
| `server.py:243-245` | **raw Exotel response body** (`resp_text`): contains the dialled number, caller id, account sid | **remove** the body; log the HTTP status only. No body, no Exotel error code (founder, r2). Code change at the source. |
| `server.py:255` | static message + traceback (E1) | keep message; variable annotations removed by C1 |
| `server.py:323` | static "Redis connected for /demo/call rate limiting" | keep |
| `server.py:382`, `418` | static message + traceback (E2, E3) | keep message; variable annotations removed by C1 |
| `server.py:413` | Telegram HTTP status | keep |
| `server.py:449, 496, 540, 544, 559` | `type(error).__name__` only (task 003) | keep |
| `server.py:490` | static "missing or invalid X-Real-IP" (no IP) | keep |
| `server.py:570`, `621` | static message + traceback (E4, E5) | keep message; variable annotations removed by C1 |
| `server.py:683, 688, 714, 745, 772` | static | keep |
| `server.py:705, 708, 727, 733, 739` | `reason`, `call_sid` via `format_call_sid` | keep |
| `server.py:750` | static message + traceback (E6) | keep message; variable annotations removed by C1 |
| `tools.py:140` | `field`, `value`, `call_sid` | mask |
| `tools.py:152` | `Redis <session_key> field=value` (`value` may be free text: `transfer_reason`; `call_outcome` is an enum) | mask; free text kept (founder, r2). Stopgap until task 008. |
| `tools.py:154` | `field`, `value`, `session_key`, redis error text | mask |
| `tools.py:220` | `book_site_visit`: `call_sid`, date, time, **`notes`** (free text from the caller) | mask; free text kept (founder, r2). **Stopgap until task 008 stores real commitments.** |
| `tools.py:237` | validation error text, `call_sid` | keep |
| `tools.py:301` | `transfer_to_human`: `reason`, **`context_summary`** (LLM summary of the call) | mask; free text kept (founder, r2). **Stopgap until task 008 stores real commitments.** |
| `tools.py:393` | `end_call`: `outcome` (enum), **`summary`** (free text) | mask; free text kept (founder, r2). **Stopgap until task 008 stores real commitments.** |
| `tools.py:417, 427` | static / `call_sid` | keep |
| `tools.py:496` | static "REDIS_URL is not set" (variable **name** only) | keep |
| `tools.py:507` | **`Redis connected ({redis_url})`**: the `redis://` line in the logs; the URL may carry a password | **remove** the URL; log "Redis connected" |
| `tools.py:510` | **`Could not connect to Redis at {redis_url}: {e}`** | **remove** `redis_url`; keep `{e}` (masked) |
| `week2_latency_observer.py:132` | `print` of latency milliseconds | keep |

**1d. Logs written by pipecat (library code we cannot edit), all through the same loguru handler**

| Library site | What it logs | Level | Decision |
|---|---|---|---|
| **P1** `pipecat/runner/utils.py:276` | `Parsed - Type: exotel, Data: {call_data}`. For Exotel `call_data` holds `from` and `to` (the **full phone numbers**), `account_sid`, `custom_parameters`. Fires once per call. **Proven** (review 1 ran pipecat's real function: full numbers with a default handler, `****3210` and `****8901` with the new one). Not in the audit list; the proven source of phone numbers in the logs. | DEBUG | mask (scrubber) |
| `pipecat/runner/utils.py:191, 201` | raw first/second WebSocket messages (also carry from/to) | TRACE | mask (scrubber); only reachable with `LOG_LEVEL=TRACE` |
| **P2** `pipecat/services/openai/base_llm.py:304-306` | `Generating chat from context {messages}`: the **whole conversation including the system prompt (which embeds the KB)**, on **every LLM call**. **Proven** (review 1 ran the real `OpenAILLMService.get_chat_completions`: the marker in the system message appeared with a default handler and did not with the new one). `get_messages_for_logging` truncates large binary values; that it truncates long **text** is **UNVERIFIED** and I assume it does not. | DEBUG | **remove**: records from this module below INFO are dropped by a handler filter (a scrubber cannot recognise "a prompt") |
| `pipecat/services/openai/base_llm.py:232` | `Using system instruction: ...` (only if `system_instruction` is set; `bot.py` passes the prompt as a message, so probably unreachable; **UNVERIFIED**) | DEBUG | **remove**: same filter |
| `pipecat/services/tts_service.py:137, 734`, `elevenlabs/tts.py:990, 1362` | `Generating TTS [text]`: the bot's own spoken sentences | DEBUG | mask (scrubber): keep, so the bot's words stay debuggable |
| `pipecat/services/llm_service.py:248-252` | "Starting N function calls" (no arguments) | INFO | keep |

Not enumerated: every other `logger.*` call in pipecat (several hundred). I checked the runner, the OpenAI LLM service, TTS, STT (`stt_service.py`, `deepgram/stt.py`), the FastAPI WebSocket transport and the Exotel serializer. I found no user-transcript logging; `UserTranscriptLogger`/`TranscriptionLogObserver` exist in pipecat but `bot.py` attaches no such observer (`bot.py:514-544`). **UNVERIFIED** for the rest: the exit-test counts are the net for those.

### 2. The change

**New `agent/log_scrub.py`** (small; ships automatically through `COPY *.py`):

- `scrub(text: str) -> str`, pure function, applies in this order:
  1. **Redis URLs**: `(rediss?|unix)://\S*` replaced by `[redis-url removed]`. The scheme is *not* kept, so the exit-test grep for `redis://` cannot match the placeholder.
  2. **Exact secret values**: for every env var whose name ends in `_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`, plus `REDIS_URL`, with a value of 8+ characters, replace that exact value with `[secret removed]`. Read from `os.environ` on each call (cheap at this log rate; tests can set a fake without cache-busting). This is the net for secrets we did not foresee, such as a token inside an exception message.
  3. **Token shapes** (defence in depth for secrets not in env): JWTs (`eyJ...` three dot-separated parts, which is the Supabase service-role key format), `sk-...` keys, Telegram `bot<digits>:<token>`, `Bearer <token>`.
  4. **Phone numbers**: Indian mobile in `+91`, `91`, `0` or bare form (`(?<![A-Za-z0-9])(?:\+91|91|0)?[6-9]\d{9}(?![A-Za-z0-9])`) and `+<10-15 digits>`, replaced by `****` + last 4 digits. The alphanumeric look-around keeps 32-hex call SIDs, timestamps and float latencies intact.
- `configure_logging(level: str | None, stream=None)`: `logger.remove()` then `logger.add(sink, level=level or "DEBUG", diagnose=False, filter=drop_prompt_debug)`. An empty or missing level means `DEBUG` (the existing default, kept per the founder); today an empty-but-set `LOG_LEVEL` would crash boot, see C5.
  - `sink(message)` writes `scrub(str(message))` to `stream or sys.stderr` (resolved at call time so tests can swap it). The sink receives the **fully formatted** text, traceback included, so the scrub also covers exception messages (E7).
  - If `scrub` raises, the sink writes a fixed placeholder line instead. Reason: loguru's default `catch=True` handler error path prints the **original unscrubbed record** to stderr.
  - `drop_prompt_debug(record)`: false when `record["level"].no < 20` and `record["name"] == "pipecat.services.openai.base_llm"`.

**`agent/bot.py:95-96`**: replace the `logger.add(...)` line with `configure_logging(os.getenv("LOG_LEVEL"))` and import it. Keep the existing comment about bare `logger.remove()`.

**`agent/server.py:243-245`**: log `resp.status` only; drop `{resp_text}`. No body and no Exotel error code (founder, r2). `resp_text` is still used for the HTTP response `detail`, unchanged. (3 lines. This is the only `server.py` edit; E1-E6 need no code change.)

**`agent/tools.py:507, 510-513`**: drop `({redis_url})` and `at {redis_url}`; messages become `Redis connected` and `Could not connect to Redis: {e}`.

**`agent/.dockerignore`**: add `test_log_hygiene.py` next to the other test modules (so it does not ship in the image).

**New `agent/test_log_hygiene.py`**: see Acceptance tests.

**Files in scope (nothing else is touched):** `agent/log_scrub.py` (new), `agent/bot.py`, `agent/server.py`, `agent/tools.py`, `agent/test_log_hygiene.py` (new), `agent/.dockerignore`, this spec, and later a `docs/memory/inbox/` note.

**Alternatives rejected**
- *Only `diagnose=False`*: removes the whole `diagnose` class (E1-E6, whichever are real) but leaves the pipecat `Parsed ... from/to` line, the pipecat prompt line, `redis_url` at `tools.py:507`, and secrets in exception messages. Insufficient on its own.
- *Raise the default `LOG_LEVEL` to `INFO`*: drops P1 and the prompt line, but also all other DEBUG diagnostics, does nothing for a VPS that sets `LOG_LEVEL` explicitly, and does not fix `tools.py:507` (INFO) or `server.py:243` (WARNING). Rejected by the founder (r2): `DEBUG` stays the default, the `base_llm` DEBUG records are dropped, everything else is scrubbed.
- *loguru `patcher`*: runs before the traceback is rendered, so it cannot scrub exception text. A sink sees the final text.
- *Regex-only, no source edits*: removing `redis_url` and the Exotel body at the source is simpler to reason about than relying on a pattern.

### 3. `/start` reachability through nginx (read-only; informs the queue item, not part of the change)

Read: `infra/nginx/api.infrasmith.dev.conf` in the repo (the repo copy, not the live file). I did not call `/start`.

- In the `server_name api.infrasmith.dev` TLS block (lines 93-205) the only locations are `/` (line 118: `try_files $uri $uri/ =404` under `root /var/www/html`), `/ws` (124, prefix, proxied to `127.0.0.1:7860`), `/demo/call` (134, prefix, proxied) and `= /contact` (157, exact, proxied). There is **no** `location` for `/start` (or `/health`).
- nginx uses the longest matching prefix, so `/start` matches none of the proxied locations and falls to `/`: a static-file lookup that returns 404 unless a file or directory named `start` exists under `/var/www/html`.
- The comment at lines 135-136 states the intent: "`/start` must remain browser-inaccessible". The port-80 blocks (21-71, 206-218) serve only the same static root, redirect to https, or return 404.
- `docker-compose.yml` publishes the agent only on `127.0.0.1:7860` (loopback).
- **So, per the repo copy, `/start` is not reachable from outside through nginx.** That is not proof. **UNVERIFIED:**
  - that the live file equals the repo copy (task 003 recorded the founder confirming only the `/demo/call` and `/contact` proxy blocks);
  - other files in `sites-enabled/` or other server blocks that could proxy `/start`;
  - whether `/var/www/html/start` exists;
  - any other path in, since the compose comment says Exotel reaches `/ws` "through a tunnel/proxy", and I cannot tell what that tunnel exposes;
  - host firewall rules.
- Consequence for the queue: "`/start` is unauthenticated" is still true in the code, but exposure through this nginx config looks closed, so the item is hardening and not an open door. Do not claim either way publicly until the live file and the tunnel are checked by the human.

## Data touched

None expected. No tables, no Redis keys, no SQL. Logging changes only.

## Acceptance tests (automated)

New file `agent/test_log_hygiene.py`, `unittest`, same import pattern as `test_demo_guard.py:333-336`. Every test captures through the **production** `configure_logging(..., stream=io.StringIO())`, not a hand-built sink, and restores the handler afterwards.

| # | Test | Asserts |
|---|---|---|
| T1 | **Secret in a local variable.** A function holds `fake_secret = "FAKE-SECRET-<random>"` as a local, raises, and the caller runs `logger.exception(...)`. | The secret is **absent** from the captured output; the exception class name and the message are **present** (the traceback is still logged). **Control:** the same function through a raw `logger.add(buf2, diagnose=True)` sink **does** show the secret. This proves the test can fail and would catch a loguru change or someone removing `diagnose=False`. |
| T1b | **Real call sites.** With fake `EXOTEL_*` env values and a session whose `post` raises: `trigger_exotel_call` (E1). Same style for `store_contact_submission` with a fake `SUPABASE_SERVICE_ROLE_KEY` (E2) and the Telegram notifier with a fake `TELEGRAM_BOT_TOKEN` (E3). | Fake key, token, Supabase key, bot token and the fake phone are absent; the static message ("Failed to connect to Exotel API" etc.) is present. |
| T1c | **Server import wiring** (`test_t1c_server_import_installs_one_safe_handler`). A fresh interpreter (minimal env: only a fake `FAKE_API_TOKEN`; `dotenv.load_dotenv` stubbed) runs `import server`, then a `logger.exception` from a function holding the fake token as a local. A control interpreter does the same with `logger.add(sys.stderr, diagnose=True)`. | Exactly one loguru handler is installed and its `diagnose` is `False`; the exception class name is present and the fake token absent. The control **does** show the token, so the test can fail. This is the only guard for `bot.py` dropping its `configure_logging(...)` call or `server.py` adding a handler of its own. |
| T2 | **Phone numbers only masked.** `scrub` over `+919876543210`, `919876543210`, `09876543210`, `9876543210`, and a pipecat-shaped line `Parsed - Type: exotel, Data: ... from='09876543210' to='+919876543210'`; also through `logger.info` and through a `logger.exception` whose message embeds a number. | Output contains `****3210`; output does not contain `987654` or the last 6 digits. **No over-masking:** a 32-hex call SID, `1730000000123`, `1234.5ms`, and `call_sid='abc1234567890def'` pass through unchanged. |
| T3 | **No `redis://`.** (a) `tools.make_redis_client` with `REDIS_URL=redis://:S3CRETPW@redis-host:6379/0`, once with `from_url`/`ping` succeeding and once failing; (b) `get_demo_redis_client` failing inside a `logger.exception` path (E4/E5); (c) `scrub("Redis URL must specify one of the following schemes (redis://, rediss://, unix://)")`. | `"redis://"` and `S3CRETPW` do not appear in any captured output; the success and failure messages are still logged. |
| T4 | **Exotel body not logged.** `trigger_exotel_call` with a mocked non-200 response whose body contains a marker string and a phone number. | Neither the marker nor the digits are in the output; the status code (e.g. `400`) is. The HTTP response to the caller is **unchanged** (same `detail`), asserted. |
| T5 | **Prompt/context DEBUG dropped.** Emit a DEBUG record whose module name is `pipecat.services.openai.base_llm` (compiled with `__name__` set to that name) carrying a marker; also a WARNING from the same name; also a DEBUG from another module. | The DEBUG marker is dropped; the WARNING and the other module's DEBUG pass. **Guard:** `importlib.util.find_spec("pipecat.services.openai.base_llm")` exists, so a pipecat upgrade that renames the module fails this test rather than silently reopening the leak. |
| T6 | **Unforeseen secret in an exception message.** Set a fake env var `FAKE_API_TOKEN=<random>`, raise `RuntimeError(f"... {token} ...")`, `logger.exception`. Also a JWT-shaped string and a `bot123456:ABC...`-shaped string with no env var. | None of the three appears. |
| T7 | **Scrubber failure cannot leak.** Patch `scrub` to raise while logging a marker. | The marker is absent from both the stream and captured `sys.stderr`; a placeholder line is present; logging does not raise. |
| T7b | **Failing output stream cannot leak** (`test_t7b_failing_stream_cannot_emit_raw_record`). `configure_logging` with a stream whose `write` always raises, then `logger.error("UNSCRUBBED-MARKER +919876543210")`, with `sys.stderr` captured. | Neither the marker nor the digits reach captured stderr (the inner `try/except` in the sink stops loguru printing `Record was: {...}`). |
| T8 | **Source guard.** Parse `server.py`, `tools.py`, `bot.py`, `demo_guard.py`, `kb_loader.py` with `ast`; find every `logger.*(...)` call. | No argument references a name in {`redis_url`, `resp_text`, `api_key`, `api_token`, `auth`, `bot_token`, `supabase_key`, `headers`}. `bot.py` contains no `logger.add(` and calls `configure_logging`. |
| T8b | **No other `logger.add`** (second guard inside `test_t8_...`). Walk every shipped `agent/*.py` (those not listed in `.dockerignore`) with `ast`. | Any `logger.add(...)` outside `log_scrub.py` fails the test, and `bot.py` source must contain `configure_logging(`. |
| T10 | **Empty level.** `configure_logging("")` and `configure_logging(None)`. | Neither raises; a DEBUG record is emitted (the default level is `DEBUG`). |

Commands (from the worktree root; `PY` per `AGENTS.md`):

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_log_hygiene
"$PY" -m unittest agent.test_demo_guard agent.test_ws_auth
"$PY" -m unittest agent.test_kb_loader        # 5 known F23 errors, no new ones
(cd agent && "$PY" -c "import server, week2_latency_observer")   # same as the Dockerfile smoke
```

The first command runs T1-T8 and T10. The other three are **PR evidence, not acceptance tests** (there is no T9): `agent.test_demo_guard` and `agent.test_ws_auth` must pass unchanged (including `test_failure_logs_exclude_phone_and_ip`), `agent.test_kb_loader` must still show exactly the 5 known F23 errors, no more, and the import smoke must succeed. The builder pastes all the output into the PR. Unit tests are **not** the gate (constraint 6); they only make the exit test cheap to pass.

## Exit test (what you do by hand on real calls)

Counts only. **Never run `docker logs` without piping to `grep -c` / `wc -l`, and never paste log lines anywhere.** Everything below runs on the VPS in a shell where you are logged in. I do not SSH.

Two batches of real calls, same procedure, same commands:

- **Batch A: baseline on the OLD code**, combined with your latency baseline calls. One batch, **one `T0` recorded before the first call of the batch.**
- **Batch B: after merge and deploy, on the NEW code.** Its own `T0`, recorded after the post-deploy health check.

**Order matters. The Batch A counts must be taken and written down before anything recreates the `nxlyr_agent` container.** A recreate deletes the old container's logs and the baseline with them (per founder; UNVERIFIED by me). So until the Batch A numbers are written down: no merge (merge = deploy), no `docker compose up`, no `--force-recreate`, no `docker rm`, no `docker compose down`.

`N` below is the number of calls in the batch being measured.

**Caps.** If the calls go through the site, `/demo/call` allows 3 per number per 24h with a 180s cooldown between calls (task 003). A batch with N > 3 to one number, or Batch B on the same day as Batch A, will be refused with 429. Raising the caps for the test, and putting them back afterwards, is 🧑 YOU via "Operator commands" in `docs/issues/003-f02-demo-call-lockdown.md`. I do not run them.

1. 🧑 YOU **Batch A (old code).** Record the start time once, before the first call of the batch:
   ```bash
   T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$T0"
   ```
   Then place your N calls, including your latency baseline calls. In at least one call, ask the bot to book a site visit (exercises `tools.py:220`), and say your own number aloud once if you are happy to. Let each call end by the bot's `end_call` or by hanging up.
2. 🧑 YOU Run the counts for Batch A (block below) and write the numbers down. **On old code the gates are expected to be non-zero**; that is the point of the baseline. Predictions, UNVERIFIED: `redis://` ≥ 1 per call (`tools.py:507`), last-6 ≥ 1 (pipecat `Parsed` line; `LOG_LEVEL` is the `DEBUG` default per founder), `Generating chat from context` ≥ 1 per LLM call; `BasicAuth`, `Bearer ` and the Telegram token shape 0 (they need an exception or a logged header, which a normal call has not produced; a non-zero here is news, tell me).
3. 🧑 YOU Send me the Batch A numbers (numbers only).
4. 🧑 YOU Merge the PR. 🤖 AGENT `deploy.yml` runs `git pull` and `docker compose up -d --build` as a pair. 👀 VERIFY container health **twice, a few seconds apart**: `docker ps --filter name=nxlyr_agent --format '{{.Status}}'`.
5. 🧑 YOU **Batch B (new code).** New `T0` (same command as step 1), taken after the health check. Place N fresh real calls, same script as step 1.
6. 🧑 YOU Run the counts for Batch B (same block).
7. 👀 VERIFY **Pass for Batch B** = both controls hold and all seven gates are 0.

The count block, identical for both batches (`read -r` keeps your number out of shell history and out of the output):

```bash
read -r N          # number of calls in this batch
read -r LAST6      # last 6 digits of your own number, then Enter
L() { docker logs nxlyr_agent --since "$T0" 2>&1; }

# controls: both must hold, otherwise a "0" below means nothing
L | wc -l                                                    # must be > 0
L | grep -cF 'Call finished'                                 # must be >= N
[ "$(L | grep -cF 'Call finished')" -ge "$N" ] && echo "control ok: finished >= N" || echo "control FAILED: finished < N"

# gates you specified: all must be 0 on Batch B
L | grep -cF 'redis://'
L | grep -cF "$LAST6"

# replaces the old `auth = ` gate (see note below): the Exotel and Supabase/Telegram credentials by shape
L | grep -cF 'BasicAuth'                                     # aiohttp.BasicAuth repr (Exotel key + token)
L | grep -cF 'Bearer '                                       # Authorization header (Supabase service-role key)
L | grep -cE 'bot[0-9]{6,}:[A-Za-z0-9_-]{20,}'               # Telegram bot token inside a URL

# two extra gates I added (kept, founder r2): must be 0 on Batch B
L | grep -cF 'Generating chat from context'                  # a prompt/context dump
L | grep -cF 'eyJ'                                           # a JWT (Supabase key shape)

# information only, not a gate: masked numbers present
# (LOG_LEVEL is the DEBUG default, so expect >= N; 0 means tell me)
L | grep -cE '\*{4}[0-9]{4}'
```

Report format, numbers only: `N=3 lines=412 finished=3 redis=0 last6=0 basicauth=0 bearer=0 tgtoken=0 prompt=0 jwt=0 masked=3`.

Notes on the controls:
- `Call finished` (`bot.py:588`) is logged only when `run_bot` returns normally. If it is **below N**, at least one call ended abnormally or the window is wrong: report the count, do not treat the batch as a pass.
- It can be **above N** if someone else used the demo in the window; that is fine, and any leak in their call counts too.
- **Why the old `grep -cF 'auth = '` gate was dead (review 2, N1).** It looked for a label. loguru's `diagnose=True` never prints `name = value`: it draws the source line and, under it, `│`/`└` marks with **only the value's repr** (checked with a toy example, loguru 0.7.3). So `auth = ` could not appear on the old code with `diagnose=True` and an exception, and `auth=0` would have read as "no leak" whether or not the fix worked. The three new gates match what a leak would actually contain: `BasicAuth` (the class name in the repr of `aiohttp.BasicAuth`, which holds the Exotel key and token), `Bearer ` (the Supabase service-role `Authorization` header), and the Telegram token shape (`grep -E`).
- **What these three gates can and cannot show.** They can fire (unlike the old one), but only if an exception repr or a logged header reaches the log. On a normal call, with no exception, they are expected to be 0 on Batch A and Batch B alike (UNVERIFIED), so a Batch B zero is weak evidence here. The failure path is carried by T1/T1b (with the `diagnose=True` control), not by the exit test. Note that on Batch B the scrubber also rewrites `Bearer <token>`, so `Bearer ` is partly a check on the scrubber itself.

8. 👀 VERIFY If any Batch B gate is non-zero: do not look at or paste the lines. Tell me which count and the time window; I will say which `grep -n` to run to get a **line number and nothing else**, and we trace it to a site.

## Risks and rollback

**Risks**
- *Over-masking.* The phone regex could mask a legitimate digit run inside free text (e.g. a booking note). Acceptable: the rule is "phone numbers masked". T2 pins the no-false-positive cases that matter (SIDs, timestamps, latencies).
- *Under-masking.* Grouped or spoken formats (`98765 43210`, "nine eight seven...") are **not** masked by the regex. Which formats Exotel puts in `from`/`to` is **UNVERIFIED**. The exit test greps the raw last 6 digits, which would catch an unmasked contiguous form; it would not catch a spaced form. Mitigation if it matters: add a separator-tolerant pattern; deferred.
- *Landline-style and toll-free numbers are not masked* (review 1, R6). The phone pattern covers Indian mobiles (`[6-9]` then 9 digits, with an optional `+91`, `91` or `0` prefix) and `+` followed by 10-15 digits. Verified **not** masked: `02212345678` and `01123456789` (0 + STD code + number), `18001234567`, digits glued to letters (`phone9876543210`), and spaced international forms (`+1 415 555 2671`). Grouped and spoken forms were already admitted above. If Exotel's `to` field (the ExoPhone, the business's own number) is landline-style, it is logged in full: **UNVERIFIED**, because what Exotel sends in `from` and `to` has not been observed. **Why we are not widening the regex now:** (1) the founder's rule and the exit gate concern personal mobile numbers, and the ExoPhone is not a caller's number; (2) a pattern like `0[1-9]\d{9}` would be a guess about formats we have not seen, and every widening raises false positives on 10-11 digit counters and IDs, so the no-false-positive test list (T2) would have to grow with it; (3) Batch B's information-only `masked=` count and the last-6 gate show whether the founder's own number slips through. If a real format escapes, widening is a small follow-up with its own test.
- *Less debuggability.* `diagnose=False` removes variable values from tracebacks; the stack and exception text remain. The pipecat prompt/context DEBUG line is gone (use `prompt_harness.py` locally for prompt debugging).
- *Free-text tool logs are a stopgap.* `tools.py:220` is described in its own docstring as the "greppable record" of a booking until real tools exist. This task keeps `notes`, `context_summary`, `summary` and `reason` (phone numbers masked), so that record survives. Founder, r2: this is a stopgap until task 008 stores real commitments; those log lines should be revisited then (not by this task).
- *Dev terminals lose colour.* The function sink does not colourise. Container output was never coloured (no TTY).
- *Loguru error path.* Handled by the placeholder in the sink (T7).
- *Merge conflict with 006* (`server.py`): this task edits only `server.py:243-245`. Whichever PR merges second rebases; I expect no overlap with `request_demo_call` (`440-580`).
- *Exit test timing.* Batch B can only run against production after merge; Batch A must run **before** the merge or the baseline is lost. Rollback below is cheap and the change is logging-only.
- *Past leaks are not undone by this task.* The old container's logs are deleted when the container is recreated (founder; **UNVERIFIED** by me), which is why the Batch A counts must be taken first. No rotation is planned (founder, r2); the founder is checking whether any log excerpt was ever pasted somewhere and will report.
- *Demo caps vs. the test batches.* `/demo/call` allows 3 calls per number per 24h with a 180s cooldown (task 003). Batch A plus Batch B to the same number inside 24h can exceed that. See the exit test.

**Rollback**
`git revert` the merge commit on a task branch (agents never push `main`), human merges, deploy runs `git pull` + `docker compose up -d --build` (inseparable pair). Check health twice. No data to restore: nothing persistent changes.

## Open questions for me

All eight answered by the founder in r2. Recorded here so the reasoning survives; the design sections above already reflect them.

1. **Free-text tool arguments** (`tools.py:220` `notes`, `:301` `context_summary` and `reason`, `:393` `summary`, `transfer_reason`). **Answer: keep, with phone numbers masked.** This is a **stopgap until task 008 stores real commitments**; the `book_site_visit` log line is the only booking record until then.
2. **Prompt dump control and `LOG_LEVEL`.** **Answer:** there is no `LOG_LEVEL` line in the VPS `.env` and the container check showed it empty, so production runs the code default `DEBUG`; the pipecat prompt line and `from`/`to` line are expected to be live today (Batch A will show it). Keep my design: `DEBUG` stays the default, drop the `base_llm` DEBUG records, scrub the rest. (My note: set-but-empty would crash boot, so it is unset; `configure_logging` accepts empty as `DEBUG`. See C5, T10.)
3. **Exotel failure body.** **Answer: log the HTTP status only.** No body, no error code.
4. **Baseline on the old code.** **Answer: yes**, combined with the founder's latency baseline calls: one batch, one `T0` before the batch. Baseline counts are taken **before any container recreate**, because a recreate deletes the old container's logs. `Call finished` must be ≥ the number of calls in the batch, not ≥ 1. All reflected in the exit test.
5. **Past leaks.** **Answer:** to the founder's knowledge no log excerpt has been pasted into a chat, issue, PR or memory file; the founder will verify and tell me if one is found. **No rotation is planned.**
6. **Dev-only scripts.** **Answer: leave them alone.**
7. **`/start`.** **Answer: yes**, add "`/start` returns the raw Exotel body to the HTTP caller" and "`/start` is unauthenticated" to the queue, **in the close-out docs PR, not in this task**. Also: read the nginx config and state whether `/start` is reachable from outside (read-only, UNVERIFIED where unknowable, no calls). Done in design section 3: per the repo copy it is not proxied and falls to a static 404; the live file, other server blocks and the Exotel tunnel are UNVERIFIED.
8. **Log rotation (new queue item, later, not this task).** `docker-compose.yml` has no log rotation (`json-file`, unbounded), so logs can fill the disk. Recorded in Non-goals. Goes on the queue in the close-out docs PR.

**Extras kept (founder, r2):** the two extra gates (`Generating chat from context`, `eyJ`) and the controls.

**Queue items for the close-out docs PR (not this task, not written yet):** (a) `/start` returns the raw Exotel body to the HTTP caller; (b) `/start` is unauthenticated, with the nginx finding from design section 3; (c) no log rotation in `docker-compose.yml`.
