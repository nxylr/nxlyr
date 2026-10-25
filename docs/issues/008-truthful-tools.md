# 008 — Truthful tools: a booking exists, and someone is told, before the bot says it is booked

**Status: APPROVED r3 (founder approved 2026-10-25; R1 to R6 accepted as written). No code written. The founder runs the main r3 SQL block only (r2 was never run, so the additive block is not used). Nothing committed.**
Worktree `../nxlyr-worktrees/008-truthful-tools`, branch `task/008-truthful-tools`, from `origin/main` at `e3dca41` (015 merged as `8b21625`). **Built on top of 018** (see "Build order").
Covers: audit F03, F04, F15, F16 (`sw_docs/NXLYR-independent-audit.md:63,64,75,76`); the 24 Oct 15-call test where one call's Redis hash lost `transfer_requested` although the tool fired (`docs/memory/log.md:25`).

## r1 to r2: what changed

| Founder answer | Effect in this spec |
| --- | --- |
| Q1 `call_commitments`, old table untouched | SQL stays on `call_commitments`. Committing the old `commitments` migration is your separate item. |
| Q2 option A, callback request, same chat, "Callback request" at the top, your two sentences | `transfer_to_human` now writes a `callback_request` row and sends an alert, like a booking. Success only if both happen. |
| Q3 wording | Sentences fixed in "Spoken wording" below. Three more sentences I had to write are marked **PROPOSED**. |
| Q4 A for success, B (fixed sentence from code) for failure and refusals | Failure and refusal sentences are spoken by code with `run_llm=False`. Success wording stays with the model. C is a separate item. |
| Q5 (a) store the number, "ends 1234" in Telegram, log which Exotel field held it | Added `pick_lead_phone` and a per-call log line. Settles which field is the lead's. |
| Q6 timeouts as proposed, visit hours 09:00 to 19:00 IST, 90-day horizon, named constants, second booking = second row (**replaced in r3**: a correction supersedes the first) | Added to validation. Two new fixed refusal sentences. |
| Q7 build on 018; edit only the transfer line; fix the prompt date; pre-call text check | See "prompt.py", "Build order" and the two corrections in "Open questions": the transfer line is **one shared constant**, not one line per variant, and editing it breaks a golden test in 018's `test_prompt_v21.py`. |
| Exit step 1 (Telegram pre-flight) | **Done, result `0`** (you, 2026-10-25, before the build): the running container has no "Telegram notifications are disabled" line. A deploy does not change `/mnt/secrets/.env`, so the result stands; exit step 5 edits it temporarily and restores it. |
| Report `db_ms` and `tg_ms` | Required in the PR; the exit test has the command. |

## r2 to r3: what changed

Source: the founder's text test of 018. A caller says "no, Saturday, not Sunday", the bot books again, and as specced that left two live rows and two alerts. R1 to R5 were accepted as written.

| Founder instruction | Effect in this spec |
| --- | --- |
| A later `site_visit` booking on the same `call_sid` replaces the earlier one; keep the earlier row | New nullable column `superseded_at`. The earlier row is kept and stamped, never deleted. |
| The new alert starts "Updated booking" and names the time it replaces | `Updated booking [ref …]` / new time / `replaces Sun 1 Nov, 11:00`. |
| The "not alerted" query ignores superseded rows; add a query that lists superseded rows | Both in "Data touched". I added a third read-only query (calls with two or more live bookings), which catches a failed supersede. |
| Test: two bookings on one call give one live row, one superseded row and an "Updated booking" alert | T24, plus T25 to T29 for the edge cases below. |
| SQL r3 with rollback | In "Data touched". |

Defaults I chose where the instruction was silent (R6): the earlier booking is superseded **only after the new one is stored and alerted**; the lookup of the earlier row happens **before** the insert; only earlier rows that were actually **alerted** are named in "replaces"; the lookup is skipped on a call's first booking. Reasons are in "`agent/commitments.py`".

## Goal

When `book_site_visit` returns success, two things are already true: a row for the visit is in Supabase, and a Telegram alert for it has been delivered to the founder's chat. If either fails, the tool returns an honest failure and the bot says plainly that it could not confirm. The same rule holds for a callback request (`transfer_to_human`). Along the way:

1. Dates and times are validated in IST. Past times, impossible times (`25:99`), times outside 09:00 to 19:00, dates more than 90 days ahead, and malformed dates are refused with a short fixed spoken reason (F15).
2. A storage failure can no longer turn into a success report (F03, F04).
3. The end-of-call flag cannot be overwritten by a slow booking or set by an `end_call` that never completes (F16).
4. `transfer_to_human` becomes an honest callback request backed by a row and an alert (Q2).
5. The prompt's "today" is the IST date, not UTC.
6. The second LLM call after a tool is removed on failure and refusal turns, and kept on success (Q4).
7. A caller who corrects a booking on the same call ends with one live booking and one superseded row, and one "Updated booking" alert (r3).

## Non-goals

- No SQL executed by an agent. You run the SQL below in the Supabase SQL Editor. Never `SELECT *` on `tenants`; nothing here reads `tenants`.
- No change to the existing `commitments` or `consents` tables, and no code that reads or writes `commitments`.
- No secret handled by an agent. The Telegram token and chat id stay in `/mnt/secrets/.env`; the code reads the two names `server.py:lifespan` already reads (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). No new variable.
- No calendar, no CRM, no lead/call rows, no WhatsApp or email to the caller. No live call bridge to a human (needs a DID and Exotel's bridge API).
- No change to how `end_call` picks its outcome (the F15 note on the `outcome` enum is left; nothing reads it yet).
- No cancel flow, and no amend-in-place. A correction is a new booking that supersedes the earlier one on the same call (r3). A booking made on a different call never supersedes anything.
- `prompt.py` edits are limited to three places: the transfer rule (one shared constant), the `today` default (IST), and `FUNCTION_RULE` only if the exit test forces it. Nothing else in 018's prompt text.
- A fixed success sentence (option C), the knowledge-base home for visit hours and horizon, a Telegram health alert, and a pager for a bad token are separate items.
- Not touching latency work from 015, turn release (011), voice config (019).

## Design (files to touch and why)

### What I read

Worktree at `e3dca41`. Pipecat lives only in the main checkout's venv, so those paths are under `nxlyr/agent/venv/lib/python3.12/site-packages/pipecat/`. I ran no command against the VPS, Supabase, Redis or Telegram, and I ran no test. **018's worktree is uncommitted and moving**: what I say about it was read from its working tree on 2026-10-25 and is UNVERIFIED until it merges.

| Where | Lines | What it showed |
| --- | --- | --- |
| `agent/tools.py` `CallResources` | 82-117 | Holds only `call_sid` and `redis`. No HTTP session, no phone: audit F03's "identity not carried". |
| `agent/tools.py` `_set_session_flag` | 130-160 | One `hset` plus one `expire` per field, each a separate round trip, errors logged and swallowed, returns nothing. A booking makes up to three calls to it and `end_call` two, so one booking-then-goodbye call spends about ten round trips on flags. |
| `agent/tools.py` `_validate_visit_date` | 168-190 | `date.fromisoformat` (on 3.12.13 it accepts `20261025` and `2026-W43-1`; I ran it in the venv), `date.today()` (process-local; the image is `python:3.12-slim`, UTC; no `TZ` in `Dockerfile` or `docker-compose.yml`). No time check at all. |
| `agent/tools.py` `book_site_visit` | 207-265 | `cancel_on_interruption=False`. Validates date, writes three flags (`end_call_tool_invoked=false` unconditionally at 250), returns `status: "booked"`. Nothing durable, nobody told. `preferred_time` is read at 220 and never checked. |
| `agent/tools.py` `BOOK_SITE_VISIT_SCHEMA` | 268-281 | `required=["preferred_date"]`. Time optional in the schema although prompt line 125 says to ask for day and time. |
| `agent/tools.py` `transfer_to_human` | 293-335 | Writes `transfer_requested=true` (313) and `transfer_reason`, returns `transfer_requested`/`bridge_connected: False`. A failed flag write is swallowed, so the result is returned either way. |
| `agent/tools.py` `end_call` | 370-446 | Default `cancel_on_interruption=True`. Writes `end_call_tool_invoked=true` at 416 **before** queuing the goodbye (431) and before `result_callback` (440). A barge-in that cancels the handler between 416 and 440 leaves the flag true on a call that continues. Shutdown hangs off `on_context_updated` (443-444). The `TTSSpeakFrame` plus `run_llm=False` pattern at 431-446 is the one the new fixed sentences reuse. |
| `agent/tools.py` `make_redis_client` | 500-540 | `socket_connect_timeout=1.0`, `socket_timeout=2.0`, ping 1.0, returns `None` on failure. |
| `agent/bot.py` `run_bot` | 359-636 | `call_data` from `parse_telephony_websocket` at 380. `CallResources(...)` built at 558. Redis closed in the `finally` at 633-634, so a flag write still in flight at hang-up can fail. The call-scoped `aiohttp` session (470) closes with the call: wrong session for a write that must outlive the call. |
| Pipecat `runner/utils.py` | 262-271 | For Exotel, `call_data` carries `from` and `to` copied from the `start` event (empty string when absent). `runner/types.py:59-84`: exposed as `call_data.from_number` and `call_data.to_number`. **Which of the two is the lead is not known from the code.** `server.py:241` sends the lead as Exotel's `"From"` on the dial request, which suggests `from`, but that is the request, not the stream event. |
| `agent/server.py` `lifespan`, `store_contact_submission`, `notify_contact_submission_via_telegram` | 100-125, 386-416, 419-452 | `app.state.session` (108) is the long-lived shared session; Telegram env read at 109-110. The house patterns for Supabase REST insert and Telegram `sendMessage`. The Telegram helper swallows everything by design, so the new alert does not reuse it. |
| `agent/demo_guard.py` | 26, 74-78, 208-223, 259-293 | `SUPABASE_TIMEOUT_SECONDS = 5.0`; `validate_phone` is exactly `\+91[6-9]\d{9}`; `_supabase_headers`, `_supabase_configuration`; `record_consent` is the "insert or raise a typed error" pattern. |
| `agent/prompt.py` at `e3dca41` | 62, 113-117, 125 | `today = today or date.today()` at 62. Tool rules at 115-117, site-visit rule at 125. |
| `agent/prompt.py` in **018's working tree** | 37-53, 170-172, 238-240, 225, 310 | The three tool rules are now module constants `FUNCTION_RULE`, `END_CALL_RULE`, `TRANSFER_TO_HUMAN_RULE`, interpolated into **both** the v2 builder (170-172) and the v21 builder (238-240). One edit to the constant changes both variants. The date default is at 310. v21 line 225 lets the bot say one short line before `book_site_visit` or `transfer_to_human`. |
| `agent/test_prompt_v21.py` in 018's tree | 70, 241-242 | A **golden copy of the v2 prompt** containing the old transfer line (70), and a check that the tool-rule constants appear verbatim (241-242). Changing the transfer rule breaks the golden test. |
| `agent/convo_config.py` in 018's tree | 1-40 | Redis hash `convo:config`, field `prompt_version` in `{v2, v21}`, default `v2`. |
| `agent/test_prompt.py` (unchanged in 018's tree) | 260-266, 279-304, 292 | `test_p07` pins the tool description strings. `test_p08` calls `book_site_visit` with `app_resources=None`, no time, and asserts `status == "booked"`: it encodes what this task removes. |
| Pipecat `services/llm_service.py` | 618-630, 1314-1381 | Interruptions cancel only calls registered with `cancel_on_interruption=True`. Handler runs after `FunctionCallInProgressFrame` is broadcast (1340). |
| Pipecat `processors/aggregators/llm_response_universal.py` | 1685-1699, 1701-1757, 1759-1800 | For an async tool a `started` message goes in at call time; the final result arrives later as a developer message. The LLM runs again on the result unless the caller is speaking (1757) or the bot is speaking (push deferred, 1783-1790). With `run_llm=False` that second run is skipped. |
| Pipecat `frames/frames.py` `TTSSpeakFrame` | 790-815 | `append_to_context` defaults to True: a fixed sentence pushed this way enters the model's context. |
| `docs/memory/inbox/2026-10-22-tool-turns-pay-a-second-llm-call.md` | all | Second call median 631 ms (baseline) and 640 ms (011 exit). Your brief gives about 720 ms on 24 Oct; I have not seen that figure in a file. |

**UNVERIFIED** (each has a test or a log line below that settles it):
- Whether the model speaks in the same assistant message as the tool call, and what it says. 018's own spec says text beside a call is spoken before the function runs (read, not run). The new `pre_call_*` log (below) measures it on real calls.
- Whether a pipeline cancel at hang-up cancels an in-flight tool handler.
- The cause of the lost `transfer_requested` on 24 Oct. Candidates, none confirmed: (a) the write raised and `_set_session_flag` swallowed it; (b) the handler was cancelled at hang-up while `redis_client.aclose()` ran (`bot.py:633`); (c) the check read the key before the write landed. The 24 Oct logs are probably gone (every merge recreates the container). I claim no root cause; the fix makes each flag write one atomic transaction and logs success or failure, so the next miss names its own cause.
- That `websocket.app.state.session` exists inside `run_bot` (Starlette's `WebSocket.app` should give the FastAPI app; not run).
- Which Exotel field holds the lead's number, and in what format (`+91…`, `0…`, `91…`). Settled by the per-call log line and exit step 2.
- That GPT-4o's text beside a tool call is rare. Settled by `pre_call_*`.
- The Supabase Postgres major version. The SQL avoids features newer than 13.
- That 018's constants, line numbers and the `convo:config` switch are final.

### New: `agent/commitments.py` (about 200 lines)

Keeps `tools.py` readable and gives the tests one thing to fake. No import of `prompt.py` or `tools.py` (so `prompt.py` can import `now_ist` from it without a cycle).

- Named constants, each with a one-line comment "moves to the knowledge base later":
  `VISIT_OPEN = time(9, 0)`, `VISIT_CLOSE = time(19, 0)`, `BOOKING_HORIZON_DAYS = 90`, `STORE_TIMEOUT_S = 3.0`, `ALERT_TIMEOUT_S = 3.0`, `COMMIT_TIMEOUT_S = 6.0`.
- `IST = timezone(timedelta(hours=5, minutes=30))`. A fixed offset on purpose: India has no DST, and it needs no `tzdata` in the slim image. `now_ist()` is a one-line function so tests can replace it.
- `parse_visit(preferred_date, preferred_time, now=None) -> (date, time) | VisitError`, checked in this order, first failure wins:
  1. date must match `^\d{4}-\d{2}-\d{2}$`, then `date.fromisoformat` (rejects compact and week forms): `date_missing`, `date_malformed`;
  2. time must match `^([01]\d|2[0-3]):[0-5]\d$`. Time is **required** (also in the schema): `time_missing`, `time_malformed`;
  3. the IST datetime must be strictly after `now_ist()`: `in_the_past`. Today with a later time is fine;
  4. the date must be no later than today (IST) plus `BOOKING_HORIZON_DAYS`: `too_far`;
  5. the time must satisfy `VISIT_OPEN <= t <= VISIT_CLOSE`, both ends allowed: `outside_hours`.
  `VisitError` carries `reason` and the fixed `say` sentence (table below).
- Fixed spoken sentences are module constants here, not inline in `tools.py`, so the wording is changed in one place. A test pins that none has a digit or any of "shortly", "soon", "right away" (the past-time sentence is the one place "today" appears; it asks a question and promises nothing), and that the hours sentence matches `VISIT_OPEN`/`VISIT_CLOSE` and the horizon sentence matches `BOOKING_HORIZON_DAYS`, so changing a constant without the sentence fails a test.
- `store_commitment(session, row) -> ref`: `POST {SUPABASE_URL}/rest/v1/call_commitments`, `Prefer: return=representation` plus `resolution=merge-duplicates` and `?on_conflict=call_sid,kind,visit_date,visit_time` for bookings (a retry updates instead of duplicating), with `superseded_at: null` in the payload so a booking that comes back (Sunday, then Saturday, then Sunday again) is live again; a plain insert for callbacks. `STORE_TIMEOUT_S` via `asyncio.timeout`. Any non-200/201 or exception raises `CommitmentError` (error type and HTTP status only; never `str(error)`).
- `send_alert(session, text)`: `POST https://api.telegram.org/bot<token>/sendMessage`, plain text (no `parse_mode`, so caller-supplied notes cannot inject markup), `ALERT_TIMEOUT_S`. Success only if HTTP 200 **and** body `ok is true`. Missing token or chat id raises `AlertError("not_configured")`. Never logs the URL or `str(error)`: the token is in the URL path and `aiohttp.ClientResponseError` prints the URL.
- `mark_alerted(session, ref)`: `PATCH …?id=eq.<ref>` setting `alert_sent_at = now()`. Failure is logged and does not change the result (the alert already went out; "not confirmed" would be false).
- `commit_visit(...)`, all under one `COMMIT_TIMEOUT_S`, each step logging its own `db_ms` or `tg_ms`:
  1. **Look up earlier live bookings, only if this call has already attempted one** (`resources.booking_attempts > 0`, an in-memory per-call counter, so the usual first booking pays no extra round trip): `GET …/call_commitments?call_sid=eq.<sid>&kind=eq.site_visit&superseded_at=is.null&select=id,visit_date,visit_time,alert_sent_at`, then drop the row with the same date and time as the new request (a repeat, not a correction). A failure here counts as a `stage=store` failure: we cannot be sure of the state, so we do not confirm.
     The lookup comes **before** the insert on purpose. With two bookings in flight at once, each can only see rows that existed before its own insert, and each insert comes after its own lookup, so they cannot supersede each other and leave zero live rows. The worst case is both staying live and two alerts; nothing is lost.
  2. Insert or upsert the new row.
  3. Alert. If the lookup found earlier rows **that had been alerted** (`alert_sent_at` not null), the text is the "Updated booking" form naming them. Earlier rows that were never alerted are superseded silently, because you never heard of them.
  4. Mark the new row alerted.
  5. **Only now** mark the earlier rows superseded: `PATCH …?id=in.(…)&superseded_at=is.null` setting `superseded_at = now()`. If the new booking failed at step 2 or 3, the earlier booking stays live (the caller was told "not confirmed", and the earlier one still stands). If this PATCH fails, the result stays `booked` (the alert, which already says "replaces", went out), a `supersede FAILED` warning is logged, and the third read-only query lists the call.
- `commit_callback(...)`: insert, alert, mark, under the same cap. Callbacks are never superseded and never supersede a booking.
- Alert texts (plain text):
  - booking: `Site visit booked [ref a1b2c3d4]` / `Sat 25 Oct 2026, 11:00 IST` / `Note: <first 200 chars, or none>` / `Phone: ends 1234`
  - correction: `Updated booking [ref a1b2c3d4]` / `Sat 31 Oct 2026, 11:00 IST` / `replaces Sun 1 Nov, 11:00` / `Note: …` / `Phone: ends 1234`. The replaced time is weekday, day, month, 24-hour time, no year. If more than one alerted row was live (only after a race), they are joined with `; `.
  - callback: `Callback request [ref a1b2c3d4]` / `Asked: <first 200 chars of reason and summary>` / `Phone: ends 1234`
  The first line differs so the two are told apart at a glance. If no number was identified, the last line is `Phone: unknown`.
- `pick_lead_phone(call_data) -> (phone | None, field, reason)`: normalise each of `from_number` and `to_number` to `+91XXXXXXXXXX` (digits only; drop a leading `0`, or a leading `91` when 12 digits long) and keep the ones that pass `demo_guard.validate_phone`. Exactly one qualifies: use it (`reason=only_valid`). Both qualify: store **null** and log `reason=both_valid` (guessing would put the wrong person in the alert). Neither: null, `reason=neither_valid`. It returns the last four digits of each field for the log only.

#### Spoken wording

| Case | Spoken by | Sentence | Status |
| --- | --- | --- | --- |
| Booking not confirmed | code, fixed, `run_llm=False` | "Sorry, I couldn't confirm that visit just now, so please don't count on it yet." | Approved Q3 |
| Callback passed on | model, told to say exactly this | "I've passed your question to a colleague. I can't connect you now, but they have it." | Approved Q2 |
| Callback not passed on | code, fixed, `run_llm=False` | "I couldn't pass that on just now." | Approved Q2 |
| Past time (`in_the_past`) | code, fixed | "That time has already gone. What time later today, or which other day, suits you?" | Approved Q3 |
| Unusable or missing time (`time_malformed`, `time_missing`) | code, fixed | "I didn't get a time I can book. Could you tell me the time again?" | Approved Q3 |
| Outside hours | code, fixed | "Site visits are between nine in the morning and seven in the evening. What time in that window suits you?" | Approved Q6 |
| Too far | code, fixed | "I can only book within the next three months. Which date in that time suits you?" | Approved Q6 |
| Missing or malformed date | code, fixed | "I didn't get a date I can book. Which day suits you?" | **PROPOSED** (R4) |
| Past *date* (an earlier day, not just an earlier time today) | code, fixed | "That day has already gone. Which day suits you?" | **PROPOSED** (R4): the approved past-time sentence says "later today", which reads wrong for yesterday |
| Booking confirmed | model | e.g. "I've put you down for Saturday at eleven in the morning, and the team has been told." The result's `next_step` allows the model to say the team has been told and forbids any time for a follow-up. | Approved Q3 |

### `agent/tools.py` (edit)

1. `CallResources` gains `http_session: Any | None = None`, `lead_phone: str | None = None` and `booking_attempts: int = 0` (incremented when a booking reaches the commit step, even if it then fails). Defaults keep any existing construction (and 018's rewritten harness, UNVERIFIED) working.
2. `_set_session_flag` becomes `_set_session_flags(resources, fields, *, if_absent=()) -> bool`: one `MULTI` pipeline (`HSET` for the fields, `HSETNX` for the `if_absent` ones, one `EXPIRE`) under `asyncio.timeout(2.0)`. Returns True/False and logs one line either way: `flags write ok call_sid=… fields=… ms=…` or `flags write FAILED call_sid=… fields=… error_type=…`. The fields of one tool now land together or not at all (the 24 Oct symptom was one flag without its neighbour).
3. `book_site_visit`, in this order:
   1. Log `pre_call_text_chars=N pre_call_done_word=yes|no|unknown`: read the assistant text in the same message as this call from `params.context`. `N` is the length. `pre_call_done_word` is `yes` if that text contains the whole word `booked`, `confirmed` or `done` (case-insensitive), else `no`, `unknown` if the context cannot be read. **The text itself is never logged.** 018's v21 prompt allows a short line such as "Let me note that down", so `N > 0` is normal and expected there; only `pre_call_done_word=yes` means a premature "booked".
   2. `parse_visit(...)`. On `VisitError`: log `TOOL book_site_visit REJECTED reason=…`; speak the fixed sentence (`TTSSpeakFrame`, `append_to_context=True`) and return `{"status": "error", "reason": …, "say": …}` with `run_llm=False`. No row, no alert.
   3. `commit_visit(...)` run as `asyncio.shield(task)` with the task held in a module-level set, so a hang-up mid-booking cannot leave a row with no alert (UNVERIFIED that Pipecat cancels the handler; the shield is cheap insurance and a test proves it).
   4. Success: flags via `_set_session_flags` (best-effort; Redis is analytics now, not the record; `site_visit_date` holds the newest booking), result `{"status": "booked", "reference": ref, "visit": "<weekday, day month, HH:MM IST>", "alert": "sent", "next_step": …}`. The model words the confirmation (Q4 A). For a correction the result adds `"replaces": "<weekday, day month, HH:MM>"` and `next_step` says: this replaces the earlier booking; confirm the new day and time in one sentence and say it replaces the earlier one; you may say the team has been told; give no time for a follow-up.
   5. `CommitmentError`, `AlertError` or timeout: log `commitment FAILED stage=store|alert|timeout …`; speak the fixed "couldn't confirm" sentence with `run_llm=False`; return `{"status": "not_confirmed", "say": …}`. Flags are **not** set to booked.
   - Decision recorded: if the row was stored but the alert failed, the row stays with `alert_sent_at` null and the caller is told "not confirmed". Nobody was told, so no follow-up is promised. The "not alerted" SQL below lists those rows.
   - With no pipeline worker (harness, tests) the fixed sentence is returned in `say` and logged as a warning instead of spoken.
4. `BOOK_SITE_VISIT_SCHEMA`: `required=["preferred_date", "preferred_time"]`. Description unchanged (`test_p07` pins "does not end the call").
5. `end_call` (F16): the `end_call_tool_invoked=true` and `call_outcome` write moves from 416-418 into `_stop_pipeline` (433-438), the moment the shutdown is actually scheduled. If a barge-in cancels the handler first, the flag is never written and the call continues truthfully. That callback fires from `on_context_updated`, milliseconds after `result_callback` and long before the goodbye audio ends, so a carrier tear-down during the closing phrase still finds the flag true.
6. `book_site_visit` writes `end_call_tool_invoked=false` with `if_absent` (`HSETNX`), never `HSET`. A slow booking that finishes after `end_call` can no longer flip true back to false (F16). `HSETNX` is atomic: no Lua, no lock.
7. `transfer_to_human` (Q2 A), in this order: log the same `pre_call_*` line; `commit_callback(...)` (row `kind='callback_request'`, `notes` = reason and summary joined, capped at 500, then alert) under the shield; on success set `transfer_requested=true` and `transfer_reason` in one transaction and return `{"status": "passed_on", "reference": ref, "alert": "sent", "bridge_connected": False, "next_step": 'Say exactly: "I\'ve passed your question to a colleague. I can\'t connect you now, but they have it." Give no time. Do not offer to connect.'}`; on any failure speak the fixed "I couldn't pass that on just now." with `run_llm=False`, return `{"status": "not_passed_on", "say": …}` and do **not** set `transfer_requested`. A second request on the same call is a second row and a second alert.
8. All prompt-visible `next_step` and fixed strings are digit-free and carry no timeframe (same rule as `test_p09`).

### `agent/bot.py` (edit, two statements)

1. At the `CallResources(...)` construction (line 558 at `e3dca41`; find it by content after merging 018, which edits other hunks of this file): add `http_session=getattr(websocket.app.state, "session", None)` and `lead_phone=` from `pick_lead_phone(call_data)`. The shared app session, not the call-scoped one at 470, because a booking must be able to finish after hang-up.
2. Log once per call, right after `call_data` is parsed (380-389), **whether or not a booking happens**: `exotel parties call_sid=… from_last4=NNNN to_last4=NNNN chosen=from|to|none reason=only_valid|both_valid|neither_valid`. Last four digits only, never the full number. This is what lets exit step 2 settle which field is the lead's from any call, including a call that books nothing. The 004 scrubber masks 10-digit numbers and its leak gate counts the last six, so four digits pass.

No other change in `bot.py`.

### `agent/prompt.py` (three edits, after 018 has merged)

Task 018 keeps two variants (`v2`, `v21`) behind the `convo:config` switch. In 018's working tree the tool rules are shared constants used by both builders, so **each edit below is made once and applies to both variants** (this corrects the Q7 premise; see R1).

1. **The transfer rule.** `TRANSFER_TO_HUMAN_RULE` (prompt.py:50-53 in 018's tree; line 117 at `e3dca41`), today:
   `- transfer_to_human only logs a request. It connects nobody and schedules nothing: say a colleague will follow up, with no time.`
   becomes:
   `- transfer_to_human passes your question to a colleague by message. It connects nobody. Say only what its result tells you, with no time.`
   The Q2 sentences live in the tool result (`next_step`) and in code, not in this line, so each exists exactly once (R2).
2. **The IST date.** The `today = today or date.today()` line in `build_system_prompt` (prompt.py:62 at `e3dca41`; 310 in 018's tree) becomes `today = today or now_ist().date()`, with `from commitments import now_ist` at the top of the file. Effect: between 00:00 and 05:30 IST the prompt's "today" and the tool's "today" are the same day. A test freezes the clock at 19:00 UTC on 24 Oct and asserts the prompt says Sunday 25 October.
3. **`FUNCTION_RULE` only if the exit test forces it.** Trigger: `pre_call_done_word=yes` on any booking or callback call, or the model promising a follow-up after `not_confirmed`/`not_passed_on`. Exact change, today:
   `- You have three real functions. Call one only when its condition is met, in the same turn you speak about it. Never say something is done unless you called the function that does it.`
   would become:
   `- You have three real functions. Call one only when its condition is met. Never say something is done unless the function's result says it is done.`
   Not applied unless triggered. (v21's pre-call line, 018 line 225, already says "Never say the thing is done until the function has returned" and stays.)

Everything else in `prompt.py` (including the site-visit rule and the [HOW IT SOUNDS] example) is untouched.

### `agent/test_prompt.py` and `agent/test_prompt_v21.py` (after 018 has merged)

- `test_prompt.py`: edit only `test_p08` (279-304). It asserts the old behaviour, so it becomes: with a valid future IST date and time and fakes it expects `booked`; with `app_resources=None` it expects `not_confirmed`.
- `test_prompt_v21.py` (018's file): the golden copy of the v2 prompt (line 70) holds the old transfer line, and the verbatim-constant check (241-242) follows the constant. I change that one golden line to the new rule text, nothing else. This file is 018's; the change is forced by the transfer-line edit and is the only edit I make to it (R1).

### `supabase/migrations/20261025000000_create_call_commitments.sql` (new, record only)

Same text as the r3 SQL in "Data touched". Committed so the repo records what you ran; never executed by an agent.

### Build order (Q7)

1. Build the rest first: `commitments.py`, `tools.py`, `bot.py` (hunks that 018 does not touch), `test_tools.py`. These do not touch 018's files except `bot.py`, at different hunks.
2. If 018 has not merged when I start, I stop before `prompt.py`, `test_prompt.py` and `test_prompt_v21.py`. Once it has: `git merge origin/main` in this worktree, re-run the full suite, and only then make the prompt and test edits above.
3. If 018 has merged already, `git merge origin/main` comes first, before any file is touched.
4. Locate the 018 constants and the `CallResources(...)` line by content, not by the line numbers in this spec.

### The second LLM call after a tool (decided, Q4)

| Turn | Today | After |
| --- | --- | --- |
| Booking confirmed | LLM call 2 words the confirmation (631 to 720 ms) | **Unchanged (A).** |
| Callback passed on | LLM call 2 | **Unchanged (A)**, told to say your exact sentence. |
| Booking not confirmed, callback not passed on | LLM call 2 would word the failure | **Fixed sentence from code (B)**: `TTSSpeakFrame` plus `run_llm=False`, the pattern at `tools.py:431-446`. No second call, and the model never gets a chance to improvise a promise. |
| Refusals (time/date) | LLM call 2 | **Fixed sentence from code (B).** |
| Fixed success sentence | | **Option C: separate item**, decided from this task's exit-test numbers. |

## Data touched

**Supabase (you run, SQL Editor).** New table `public.call_commitments`. Code looks up, inserts or upserts, and patches `alert_sent_at` and `superseded_at`, with the service-role key through REST; nothing else reads it. No existing table is altered. `commitments`, `consents`, `tenants`: not touched.

**Read-only inspection of the old table (optional now; Q1 settled):**

```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'commitments'
order by ordinal_position;
```

**SQL r3 for your review. Not run.**

```sql
-- 008 r3: durable record of what the bot promised on a call.
-- A row means "the bot took this booking or callback request".
-- alert_sent_at set means "a human alert was delivered".
-- Both are needed before the bot may say it is booked or passed on.
-- superseded_at set means "a later booking on the same call replaced this one";
-- the row is kept for the record. null means live.
-- Server-only: browsers never receive a Supabase key. Run in the Supabase SQL Editor.
-- Does not touch the existing public.commitments table.

begin;

create extension if not exists pgcrypto;

create table if not exists public.call_commitments (
  id               uuid primary key default gen_random_uuid(),
  created_at       timestamptz not null default now(),
  kind             text not null default 'site_visit'
                     check (kind in ('site_visit', 'callback_request')),
  project_slug     text not null,                      -- 'nxlyr-demo' (bot.py KB_PROJECT_SLUG)
  call_sid         text not null,                      -- Exotel CallSid; the only call identifier the bot has
  visit_date       date,                               -- IST calendar date the caller asked for (site_visit only)
  visit_time       time,                               -- IST wall-clock time the caller asked for (site_visit only)
  notes            text check (notes is null or char_length(notes) <= 500),
                                                       -- site_visit: caller's note; callback_request: reason and summary
  phone_normalized text check (phone_normalized is null or phone_normalized ~ '^\+91[6-9][0-9]{9}$'),
                                                       -- the lead's number, or null if the code could not tell which Exotel field held it
  alert_sent_at    timestamptz,                        -- null = row exists but nobody was told (the caller was told "not confirmed" / "couldn't pass that on")
  superseded_at    timestamptz,                        -- null = live; set when a later booking on the same call replaced this one
  constraint site_visit_needs_when
    check (kind <> 'site_visit' or (visit_date is not null and visit_time is not null)),
  constraint superseded_only_site_visit
    check (superseded_at is null or kind = 'site_visit'),
  -- a retry of the same booking updates this row instead of adding a second one
  constraint call_commitments_retry_key unique (call_sid, kind, visit_date, visit_time)
);

create index if not exists call_commitments_created_at_idx
  on public.call_commitments (created_at desc);

create index if not exists call_commitments_unalerted_idx
  on public.call_commitments (created_at desc)
  where alert_sent_at is null and superseded_at is null;

alter table public.call_commitments enable row level security;

revoke all on table public.call_commitments from anon, authenticated;
grant select, insert, update on table public.call_commitments to service_role;

commit;
```

What changed from r2: the column `superseded_at`; the check `superseded_only_site_visit`; the "unalerted" partial index now also requires `superseded_at is null`. Everything else is as r2.
(The `unique` constraint treats two NULL `visit_time` values as different. That cannot happen for `site_visit`, because `site_visit_needs_when` forces both fields. For `callback_request` it is intended: callbacks are plain inserts, a second request is a second row.)

**If you had already run r2** (the table exists without the new column), run this instead of the block above:

```sql
begin;
alter table public.call_commitments add column if not exists superseded_at timestamptz;
alter table public.call_commitments
  add constraint superseded_only_site_visit check (superseded_at is null or kind = 'site_visit');
drop index if exists public.call_commitments_unalerted_idx;
create index call_commitments_unalerted_idx
  on public.call_commitments (created_at desc)
  where alert_sent_at is null and superseded_at is null;
commit;
```

Rollback for that incremental block (keeps the table and its rows):

```sql
begin;
alter table public.call_commitments drop constraint if exists superseded_only_site_visit;
drop index if exists public.call_commitments_unalerted_idx;
create index call_commitments_unalerted_idx
  on public.call_commitments (created_at desc) where alert_sent_at is null;
alter table public.call_commitments drop column if exists superseded_at;
commit;
```

**Rollback of the whole table (run only if needed; export rows first, this deletes them):**

```sql
begin;
drop table if exists public.call_commitments;
commit;
```

**Read-only views of the new rows (named columns only; safe any time):**

```sql
-- the latest rows, live and superseded
select id, created_at, kind, call_sid, visit_date, visit_time,
       left(notes, 80) as notes, right(phone_normalized, 4) as phone_ends,
       alert_sent_at, superseded_at
from public.call_commitments
order by created_at desc
limit 20;

-- 1. rows stored but never alerted and still live
--    (the caller was told it was not confirmed or not passed on); superseded rows are ignored
select id, created_at, kind, call_sid, visit_date, visit_time
from public.call_commitments
where alert_sent_at is null and superseded_at is null
order by created_at desc;

-- 2. rows that a later booking on the same call replaced
select id, created_at, superseded_at, call_sid, visit_date, visit_time, alert_sent_at
from public.call_commitments
where superseded_at is not null
order by superseded_at desc;

-- 3. calls with two or more live bookings (should be empty; a failed supersede or two simultaneous bookings shows here)
select call_sid, count(*) as live_bookings
from public.call_commitments
where kind = 'site_visit' and superseded_at is null
group by call_sid
having count(*) > 1;
```

**Redis (existing key, no new key).** `session:call:{call_sid}` hash, 4 h TTL, fields `site_visit_booked`, `site_visit_date` (now an IST date), `end_call_tool_invoked`, `transfer_requested`, `transfer_reason`, `call_outcome`. Written in one transaction per tool. Nothing reads them yet (`architecture.md:15`).

**Telegram.** One `sendMessage` per confirmed booking and per passed-on callback, to the existing chat. Env names `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, already used by `server.py:109-110`.

**Personal data.** The row holds the lead's number (service-role-only table). Telegram gets only the last four digits and up to 200 characters of what the caller said.

## Acceptance tests (automated)

New `agent/test_tools.py`, `unittest`, no network, no real Redis: fakes for the aiohttp session (records URL, headers, body; can return a status, raise, or sleep), Redis (implements `pipeline`, `hset`, `hsetnx`, `expire`; can raise), a worker (records frames), and `now_ist`. A real `pipecat` `LLMContext` is used for the pre-call tests so the real accessor is exercised. Run:

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_tools
```

| # | Test | Settles |
| --- | --- | --- |
| T01 | `parse_visit` refuses `25:99`, `24:00`, `9:5`, `11.30`, `11:30pm`, `""`, `None`; refuses dates `20261025`, `2026-W43-1`, `2026-10-25T11:00`, `2026-13-01`, `""`. | F15 |
| T02 | With `TZ=America/Los_Angeles` set and `time.tzset()` called, results are unchanged: IST, not the process zone. With the clock at 19:00 UTC on 24 Oct (00:30 IST on 25 Oct), `2026-10-24` is refused and `2026-10-25 09:00` accepted. | F15 IST |
| T03 | Same-day past time refused; one minute ahead accepted; exactly now refused. | F15 |
| T04 | Hours: `08:59` refused, `09:00` accepted, `19:00` accepted, `19:01` refused (`outside_hours`). Horizon: today + 90 days accepted, + 91 refused (`too_far`). Check order: a past time outside hours reports `in_the_past`; a far date at 03:00 reports `too_far`. | Q6 |
| T05 | Fixed sentences: each is spoken as a `TTSSpeakFrame` through the worker with `run_llm=False`; none contains a digit or "shortly", "soon", "right away" (the past-time sentence is exempt only from the word "today"); the hours and horizon sentences agree with the constants; with no worker the sentence is returned in `say` and a warning is logged. | Q3, Q4 |
| T06 | Happy booking: one insert (payload has `project_slug`, `call_sid`, `visit_date`, `visit_time`, `phone_normalized`, no `end_call` fields), then one Telegram call, then one patch, then the result; the order is asserted from the fake's call log. `status == "booked"`, `reference` present, `run_llm` not suppressed (model words it). | Goal |
| T07 | Insert fails (HTTP 400, 500, timeout, exception, env missing): no Telegram call; result `not_confirmed`; the word "booked" appears nowhere in the result; the fixed sentence is spoken with `run_llm=False`; `site_visit_booked` is not written. | F03, F04 |
| T08 | Alert fails (HTTP 400, 200 with `ok:false`, timeout, token missing): result `not_confirmed`; row inserted and not patched; flags not set to booked. | F03 |
| T09 | Alert succeeds, patch fails: result stays `booked`, one warning logged. | decision above |
| T10 | A retry with the same call, date and time sends `resolution=merge-duplicates` and `on_conflict=call_sid,kind,visit_date,visit_time`. A second booking at a different time is a new row and supersedes the first (T24). | Q6 |
| T11 | Redis down or raising, Supabase and Telegram fine: booking still `booked`; one `flags write FAILED` line. | F04 |
| T12 | F16 race, both orders: `book_site_visit` held slow by the fake, `end_call` run concurrently; final `end_call_tool_invoked == "true"` whichever finishes last. | F16 |
| T13 | `end_call` handler cancelled after the goodbye is queued but before `result_callback`: `end_call_tool_invoked` not written. Normal path: written exactly when `_stop_pipeline` runs. | F16 |
| T14 | `book_site_visit` task cancelled mid-flight: insert and alert still complete (shield). Same for `transfer_to_human`. | hang-up safety |
| T15 | Book and transfer in the same turn, `asyncio.gather`, 200 repetitions against the fake Redis: both `site_visit_booked` and `transfer_requested` present every time. | 24 Oct symptom |
| T16 | Callback: success writes a `callback_request` row with notes capped at 500, sends an alert whose **first line is `Callback request`**, patches, sets both flags in one transaction, and returns `passed_on` with the exact Q2 sentence in `next_step`. Store failure and alert failure each speak "I couldn't pass that on just now." with `run_llm=False`, return `not_passed_on`, and leave `transfer_requested` unset. | Q2 |
| T17 | Alert text: booking alert starts `Site visit booked`, the correction alert starts `Updated booking`; all alerts contain `Phone: ends NNNN` (or `unknown`) and never the full number or any run of ten digits; notes truncated to 200 characters; sent without `parse_mode`. | Q5 |
| T18 | `pick_lead_phone`: `from` valid and `to` a landline → `from`; `to` valid and `from` a landline → `to`; both valid → `None`, `both_valid`; neither → `None`, `neither_valid`; accepts `+919876543210`, `09876543210`, `919876543210`; empty strings. The per-call log line contains only the last four digits of each field. | Q5 |
| T19 | Pre-call log with a real `LLMContext`: assistant text "Let me note that down." → `pre_call_text_chars=22 pre_call_done_word=no`; "I've booked that." / "All done." / "Confirmed." → `yes`; "undone" and "Bookings" → `no` (whole word only); no text beside the call → `0` and `no`; context absent → `unknown`. The text is never in any log record. | Q7 |
| T20 | Log hygiene on every failure path: no captured log record contains the fake token, the chat id, any phone number beyond four digits, the Supabase key, or `str()` of an aiohttp error. | secrets |
| T21 | Latency caps: with a fake Supabase that sleeps 10 s, the tool returns `not_confirmed` within `COMMIT_TIMEOUT_S` (patched to 0.2 s so the test is fast); each log line carries `db_ms` and `tg_ms`. | no long silence |
| T22 | Schema: `required == ["preferred_date", "preferred_time"]`; descriptions still satisfy `test_p07`. | contract |
| T23 | Prompt (after the 018 merge): with the clock at 19:00 UTC on 24 Oct, `build_system_prompt(today=None)` says Sunday 25 October, in **both** `v2` and `v21`; both variants contain the new transfer rule once and not the old one. | IST date, Q2 |
| T24 | **Two bookings on one call** (Sun 1 Nov 11:00, then Sat 31 Oct 11:00): the fake table ends with two rows, exactly one live (Saturday, `superseded_at` null) and one superseded (Sunday, `superseded_at` set, row kept). The first alert starts `Site visit booked`; the second starts `Updated booking` and contains `replaces Sun 1 Nov, 11:00`. For the second booking the call order is lookup, insert, alert, mark alerted, supersede patch; the supersede patch comes after the alert. | r3 |
| T25 | Flip-flop, Sun then Sat then Sun again: the third booking's upsert payload has `superseded_at: null`, so Sunday is live, Saturday is superseded, and the third alert says it replaces Saturday. | r3 |
| T26 | The second booking fails at the insert, and separately at the alert: the first row is **not** superseded, the caller gets the fixed "couldn't confirm" sentence, and no supersede patch is sent. | r3 |
| T27 | The earlier row was never alerted (`alert_sent_at` null): it is superseded silently and the new alert is the plain `Site visit booked`, not "Updated booking". | r3 |
| T28 | The supersede patch fails: result stays `booked`, one `supersede FAILED` warning, and the alert had already said "replaces". | r3 |
| T29 | Lookup rules: the first booking on a call sends **no** lookup (zero GETs); a repeat of the same date and time is not treated as a correction; two bookings whose lookups both run before either insert end with both live and neither superseded (never zero live rows); a callback request is never superseded by, or superseding, a booking. | r3 |

Existing suites must still pass, with the `test_p08` edit and the one golden-line edit in `test_prompt_v21.py`: `agent.test_prompt`, `agent.test_prompt_v21`, `agent.test_convo_config`, `agent.test_stt_keyterms`, `agent.test_prompt_harness` (018's), `agent.test_startup_timing`, `agent.test_ws_auth`, `agent.test_demo_guard`, `agent.test_log_hygiene`, `agent.test_kb_loader`, `agent.test_turn_release`; and the import smoke `(cd agent && "$PY" -c "import server, week2_latency_observer")`.
Gates: `git diff origin/main --stat -- agent/prompt.py` shows only the three edits above; `git diff origin/main -- agent/prompt.py` contains no change to the site-visit rule, the [HOW IT SOUNDS] block, or either variant's other text; `FUNCTION_RULE` unchanged unless the exit test triggered it.

## Exit test (what I do by hand on real calls or infrastructure, with exact commands)

Tags: 🧑 YOU, 🤖 AGENT, 👀 VERIFY. Do not edit `.env` while a call is in flight.

**0. Before merge.**
1. 🧑 YOU answer the remaining items in "Open questions" (R1 to R5), and approve r3.
2. 🧑 YOU review the r3 SQL and run it in the Supabase SQL Editor. 👀 VERIFY the table exists:
   ```sql
   select column_name, data_type from information_schema.columns
   where table_schema = 'public' and table_name = 'call_commitments' order by ordinal_position;
   ```
3. 🧑 YOU merge (merge = deploy). 👀 VERIFY the container is healthy twice, a few seconds apart.

**1. Telegram pre-flight. DONE (you, 2026-10-25, before the build): `0`.** No change to `.env` is made by a deploy. Optional 5-second re-check after the deploy:
```bash
ssh nxlyr-vps "docker logs nxlyr_agent 2>&1 | grep -c 'Telegram notifications are disabled'"
```

**2. Happy path, one real call (run it once on v2; once more on v21 after 018's switch is live).** 🧑 YOU place a demo call and say: "Yes, I'd like to see it. Tomorrow at eleven in the morning." Let the bot confirm; do not hang up for a few seconds.
- 👀 VERIFY the Telegram alert arrives on your phone: first line `Site visit booked`, tomorrow's IST date and 11:00, `Phone: ends` plus the last four digits of your number, within a few seconds of the bot's confirmation.
- 👀 VERIFY by ear: the bot says the day and time, and may say the team has been told. It gives no time for a follow-up.
- 👀 VERIFY the row (the read-only view above): one new `site_visit` row, `visit_date` tomorrow, `visit_time` 11:00:00, `phone_ends` your last four digits, `alert_sent_at` not null.
- 👀 VERIFY the logs, same call:
  ```bash
  ssh nxlyr-vps "docker logs nxlyr_agent -t 2>&1 | grep -E 'exotel parties|TOOL book_site_visit|commitment (stored|alert|FAILED)|pre_call_|flags write'"
  ```
  Pass: an `exotel parties` line near the start of the call; then `pre_call_text_chars=… pre_call_done_word=no`; a `commitment stored … db_ms=…` line; a `commitment alert sent … tg_ms=…` line; then `TOOL book_site_visit result status=booked`.
  - **Which Exotel field is the lead (Q5):** compare `from_last4` and `to_last4` with the last four digits of your own number. Write down which field matched and what `chosen=` said. If `chosen=none` (`both_valid` or `neither_valid`) the row has no number: tell me, and I add a rule from what you saw.
  - **Premature "booked":** `pre_call_done_word=yes` on any booking or callback call means the bot spoke before the result existed; tell me, because that triggers the `FUNCTION_RULE` edit. `pre_call_text_chars` above 0 with `done_word=no` is normal on v21 and is not a failure.

**2b. Correction, one real call.** 🧑 YOU place a demo call and book "Sunday at eleven in the morning" (use the next Sunday). Let the bot confirm. Then say "No, Saturday, not Sunday." and let it confirm again.
- 👀 VERIFY the phone: two alerts. The first starts `Site visit booked` with the Sunday time. The second starts `Updated booking`, shows the Saturday time, and has a line `replaces Sun …, 11:00` naming the Sunday you booked.
- 👀 VERIFY by ear: the bot confirms Saturday, says it replaces the earlier one, may say the team has been told, and gives no time for a follow-up.
- 👀 VERIFY in the SQL Editor with the three read-only queries below: the first lists only Saturday as live; the **superseded** query lists the Sunday row with its `superseded_at`; the **two live** query returns no row for this call.
- 👀 VERIFY the log shows the order for the second booking:
  ```bash
  ssh nxlyr-vps "docker logs nxlyr_agent -t 2>&1 | grep -E 'commitment (stored|alert sent)|supersede'"
  ```
  Pass: for the second booking a `commitment stored` line, then `commitment alert sent`, then a `supersede ok` line, and no `supersede FAILED`.

**3. Refusals (one call, five cases).** 🧑 YOU call, agree to a visit, and give in turn: (a) a time already gone today (if it is 14:00 IST, "today at nine in the morning"); (b) "tomorrow at ten at night"; (c) a date about six months away; (d) optionally "twenty-five hundred hours".
- 👀 VERIFY by ear: after each, the exact fixed sentence from "Spoken wording" (past time; hours; three months; for (d) either the unusable-time sentence or the bot corrects itself first, both fine). The bot never says booked.
- 👀 VERIFY: no new row, no alert, and
  ```bash
  ssh nxlyr-vps "docker logs nxlyr_agent -t 2>&1 | grep 'REJECTED'"
  ```
  shows `in_the_past`, `outside_hours`, `too_far` (and `time_malformed` if (d) reached the tool).
- The `25:99` guarantee is T01; speech rarely produces it.

**4. Forced failed write (database), booking and callback in one call.**
1. 🧑 YOU run in the SQL Editor (every insert into the new table now fails; nothing else is affected):
   ```sql
   alter table public.call_commitments add constraint force_fail check (false) not valid;
   ```
2. 🧑 YOU place a call, book a visit as in step 2, then say "Can I speak to a manager?".
3. 👀 VERIFY by ear: the bot says exactly "Sorry, I couldn't confirm that visit just now, so please don't count on it yet." and, for the manager request, "I couldn't pass that on just now." It promises no call, message or time.
4. 👀 VERIFY: no alert on your phone, no new row, and
   ```bash
   ssh nxlyr-vps "docker logs nxlyr_agent -t 2>&1 | grep -E 'commitment FAILED'"
   ```
   shows `stage=store` twice, with an HTTP status.
5. 🧑 YOU undo it and confirm:
   ```sql
   alter table public.call_commitments drop constraint force_fail;
   select conname from pg_constraint where conrelid = 'public.call_commitments'::regclass;
   ```
   Pass: `force_fail` is not listed.

**5. Forced failed alert.** 🧑 YOU only; I never touch the file:
1. `ssh nxlyr-vps`, then `sudo nano /mnt/secrets/.env`. Note the current `TELEGRAM_CHAT_ID` privately, set it to `1`, save.
2. `cd /opt/nxlyr && docker compose up -d --no-deps --force-recreate agent` (recreates only the agent, not redis). 👀 VERIFY healthy twice.
3. Place a call, book a visit, then ask for a manager. 👀 VERIFY by ear: the same two fixed sentences as step 4. 👀 VERIFY: no alert; two rows with `alert_sent_at` null (the second SQL query in the read-only block: one `site_visit`, one `callback_request`); the log shows `stage=alert` twice.
4. Restore the real chat id, repeat the recreate command, 👀 VERIFY healthy twice, and place one more booking call. Pass: the alert arrives and the row has `alert_sent_at`.

**6. Flags, callbacks and the end-flag race.** Five calls. Each: "I'd like a visit tomorrow at eleven, and I also want to speak to a manager." (both tools in one turn). On two of them, say "okay, bye" right after the bot confirms the booking. You will get ten alerts (five `Site visit booked`, five `Callback request`).
```bash
ssh nxlyr-vps 'for k in $(docker exec nxlyr_redis redis-cli --scan --pattern "session:call:*"); do echo "$k"; docker exec nxlyr_redis redis-cli HMGET "$k" site_visit_booked end_call_tool_invoked transfer_requested call_outcome; done'
ssh nxlyr-vps "docker logs nxlyr_agent 2>&1 | grep -c 'flags write FAILED'"
```
Pass: for all five keys `site_visit_booked=true` and `transfer_requested=true`; the two goodbye calls also show `end_call_tool_invoked=true`; the three others show `false`; `flags write FAILED` is `0`; the read-only view shows five `site_visit` and five `callback_request` rows, all with `alert_sent_at`. If a flag is missing, the log names the cause (`flags write FAILED … error_type=…`, or no `flags write ok` line, which means the handler never finished): read the lines for that `call_sid` yourself and send them to me. Ignore keys older than the test.

**7. Callback wording, one call.** Ask only "Can I speak to your manager?" 👀 VERIFY by ear: "I've passed your question to a colleague. I can't connect you now, but they have it." (model-delivered, so check it is the sentence and not a paraphrase) and no time. 👀 VERIFY the alert's first line is `Callback request`.

**8. Wait times, for the PR.** After all calls:
```bash
ssh nxlyr-vps "docker logs nxlyr_agent 2>&1 | grep -E 'commitment (stored|alert sent)' | grep -o -E '(db_ms|tg_ms)=[0-9]+'"
```
I put every `db_ms` and `tg_ms` value, with min, median and max, in the PR. If any booking took more than 6 s the log shows `stage=timeout`; that is a finding, not a pass.

## Risks and rollback

- **One more thing must work for a booking to be "booked".** Supabase, Telegram and the token all have to be healthy. A Telegram blip makes a good booking sound unconfirmed (your decision). Mitigation: exit step 1, the "not alerted" query, `commitment FAILED` lines. Nothing pages you when the token is bad: out of scope.
- **The caller may wait up to 6 s.** `COMMIT_TIMEOUT_S` caps it; typical time is UNVERIFIED (no Supabase or Telegram timing from the VPS exists in the repo). Step 8 reports the real numbers.
- **Speech before the result.** If the model says "booked" in the same message as the call, the caller hears it before any write exists, and no code can unsay it. `pre_call_done_word` measures it; `FUNCTION_RULE` is the fix. It is why the failure path says "couldn't confirm" explicitly instead of relying on silence.
- **Fixed sentences spoken by code can talk over a caller** who is mid-sentence (a `TTSSpeakFrame` is queued; an interruption can cut it). The failure/refusal turns are rare.
- **A stored row with no alert.** After an alert failure the row exists while the caller was told "not confirmed" or "couldn't pass that on". Intended and visible; a human reconciles it.
- **Wrong person in the alert.** `pick_lead_phone` stores nothing when both Exotel fields look like mobiles. The alert then says `Phone: unknown`. Step 2 settles the field; a follow-up can make the rule deterministic.
- **Telegram token in the URL.** `aiohttp` error text contains the URL. The code never logs `str(error)`; T20 pins it. The 004 scrubber's token pattern is only a second line of defence.
- **Merge with 018.** Both tasks edit `bot.py` (different hunks), and 018's tests pin the old transfer text (R1). Order is fixed in "Build order". If 018's constants have changed shape by merge time, I re-read them before editing and report.
- **`test_p08`.** Edited because it asserts the behaviour this task removes. No other test in `test_prompt.py` is changed.
- **Required time.** The schema now makes `preferred_time` required. Prompt line 125 already says to ask for day and time before calling, so this should cost nothing; a call without a time gets the unusable-time sentence.
- **Supersession errs toward keeping a booking live.** A failed new booking never supersedes the old one; a failed supersede patch, or two bookings in flight at the same instant, can leave two live rows and two alerts, and the "two live" query finds them. It cannot leave zero. The per-call counter lives in memory, which is correct because a call lives in one process; a booking counted but not stored costs one harmless extra lookup.
- **One more round trip on a correction.** A second booking on a call pays one extra Supabase lookup and one patch inside the same 6 s cap. The first booking pays none.
- **Cancellation behaviour is read, not run.** T13 and T14 test it against fakes; real Pipecat behaviour at hang-up is confirmed only by exit steps 2 and 6.
- **Rollback.** Code: revert the PR (a revert is also a deploy); tools go back to log-only behaviour. The table is harmless to leave. Data: the `drop table` block above, after exporting rows you want. The Redis flag format is unchanged, so no reader breaks. No `.env` change is needed either way (step 5 edits it temporarily; restore it). The `prompt.py` edits revert with the PR; the IST date change has no data effect.

## Open questions for me

**Q1 to Q7 are answered and built into the sections above.** Remaining, each a yes/no or a pick. Defaults apply if you say nothing.

- **R1. Q7 correction (two facts).** (a) In 018's working tree the transfer rule is **one shared constant** (`TRANSFER_TO_HUMAN_RULE`, prompt.py:50-53) interpolated into both the v2 and v21 builders, so there is one edit, not one per variant. (b) 018's `test_prompt_v21.py:70` holds a golden copy of the v2 prompt with the old transfer line and checks the constants verbatim (241-242), so changing the rule breaks that test. I propose changing that one golden line in 018's file after 018 merges, and nothing else in it. Default: yes.
- **R2. Where the Q2 sentences live.** I put the two Q2 sentences in the tool result and in code, and the prompt line only says "Say only what its result tells you, with no time", so each sentence exists once. If you want the sentences in the prompt line as well, say so. Default: result and code only.
- **R3. Boundaries.** Hours are inclusive at both ends (a 19:00 visit is accepted, 19:01 refused); the horizon is inclusive (today plus 90 days is accepted, 91 refused). Default: as written.
- **R4. Two sentences I wrote that you have not seen.** Missing or malformed date: "I didn't get a date I can book. Which day suits you?" A past date (an earlier day, not just an earlier time today): "That day has already gone. Which day suits you?" (the approved past-time sentence says "later today", which reads wrong for yesterday). Default: use both.
- **R6. Defaults I chose for corrections (r3), none blocking.** (a) The earlier booking is superseded only after the new one is stored **and** alerted, so a failed correction leaves the old booking standing. (b) Only earlier rows that had been alerted are named in "replaces". (c) If the lookup itself fails, the booking is reported as not confirmed. (d) A callback request is never superseded. Say if you want any of these the other way.
- **R5. Lead phone rule.** Store the number when exactly one of `from`/`to` is an Indian mobile; store null when both or neither are, and say so in the log. The first real call tells us which field is right. Default: as written.

## Amendments after review (founder-approved)

The r3 body above is unchanged. Three review rounds (Claude reviewing Codex's diff) changed the build in these ways; where they differ from the text above, this section wins.

- **Scope widened to `agent/log_scrub.py`.** Pipecat logs every tool argument at DEBUG (`Calling function [...] with arguments {...}`), which carries the model's notes, reasons and summaries. `drop_prompt_debug` now also drops that one line. Everything else in the log, including all INFO and above, is kept.
- **Lead-phone rule.** "Exactly one of `from`/`to` is an Indian mobile" is replaced by "the lead is the party that is not our own `EXOTEL_PHONE_NUMBER`". The comparison is digit-normalised, and the `+91` mobile check then applies only to the other party. Unknown or ambiguous cases store null and log a reason with no phone digits. Reason: Exotel numbers such as 080-series landlines pass the mobile pattern, so the old rule would have left the number null on most calls.
- **One retained background task.** The commit (lookup, insert, alert), the alert marker, the supersede and the Redis flags run in one module-held task per tool call. The caller-facing result is published the moment the alert succeeds, so a slow marker or supersede cannot turn a delivered booking into "not confirmed", and a hang-up cannot cancel the marker, the supersede or the flags. This replaces "all under one `COMMIT_TIMEOUT_S`" for the steps after the alert; the 6 s cap now covers lookup, insert and alert only.
- **No model or caller free text in any tool log line.** `end_call` logs the outcome kind and `summary_chars`; booking and callback lines carry only kinds, references, lengths and call ids. Failure lines carry measured `db_ms` and `tg_ms`.

Smaller fixes: a missing `call_sid` is refused; non-ASCII digits are rejected by `parse_visit`; spaced or hyphenated phone numbers are redacted from notes; wrapped errors drop the raw exception chain; the Redis flag write is capped at 0.25 s and happens after the result.
