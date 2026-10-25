# 018 — Conversation v2.1: sound like a person again, hear the project name and amounts

**Status: r3 APPROVED by the founder. Spec only: no code written yet.** Approval also settled the open questions (see "Open questions" and the notes below).
Worktree `../nxlyr-worktrees/018-conversation-v21`, branch `task/018-conversation-v21`, from `origin/main` at `e3dca41` (contains 015, merged as 8b21625).

**What r3 changes against r2** (r2 and r1 content is otherwise kept):

1. **The three long samples are now eight-word versions** (table "Samples, r2 against r3" in Change 1). Every sample's first sentence is eight words or fewer; a test enforces it.
2. **Exit test:** one uncounted **warm-up call** before block 1; blocks run back to back with a snapshot after each; no interleaving and no new tool option. A **pre-agreed cut rule**: if block 2's LLM first-token p50 is more than 50 ms above block 1's, cut the correction rule first, then [HOW THE CALL GOES]; the unclear-audio rule stays.
3. **Sources:** the Softcery article was fetched and is cited for what it actually says; Jefferson 1983 stays as the source of "embedded correction".
4. **Stand-in KB:** nothing is reconstructed. `kb_meridian_heights.json` is exactly the full config you pasted (reproduced verbatim in Change 6). The paste shows digits still in the KB outside the five spoken lines (finding F-g), so the harness gets scenario S10.
5. **Sizes re-measured** with the new samples: 8,364 characters empty-KB (cap 8,664) and 11,547 with the real KB, against 4,771 and 7,948 for v2.
6. **Open questions** are answered with marked recommendations of mine; none blocks the build.

Earlier changes (r2 against r1): runtime switches in Redis `convo:config`; Deepgram EU endpoint behind `stt_region`; prompt items a to h; tagged greeting off by default; harness additions; exit test redesigned by block; public sources cited.

## Goal

Make Aarya sound like a person again without losing anything prompt v2 fixed, and make her hear the project name and amounts correctly. Let the founder make real calls on v2.1 before it becomes the default, and see what each piece changes.

It covers the 24 Oct 014 exit-test misses and the speech-recognition findings:

1. Natural by ear 5 to 6 of 10, against a bar of 7. Replies are terse and grudging: no connectives, a fact and then silence, almost no closing questions.
2. First-sentence wait p50 145 ms, against 74 ms (22 Oct) and 76 ms (23 Oct).
3. Call 3 re-introduced itself mid-call: "that sounds expensive" got "hi my name is Aarya" (a zero-tolerance miss).
4. "Hi Aarya" from the caller is not handled.
5. "Meridian Heights" heard as "Eridian Heights" (inbox `2026-10-23-meridian-heard-as-eridian.md`).
6. Amounts in crore misheard (inbox `2026-10-22-baseline-amounts-misheard-on-4-of-10-calls.md`); the crore mispronunciation on call 9 is the model reading digits from the KB (inbox `2026-10-24-kb-digits-read-aloud-crore-mispronounced.md`), fixed by the `spoken` fields.

Founder decisions carried out as written:

- **Still banned:** content-free acknowledgements of the caller ("Great", "I see", "Sure thing", "Absolutely", "Fair question", "I hear you", "Got it", "Understood").
- **Allowed, sparingly, never a reflex:** connectives ("So", "Okay so", "Right, so") and process phrases ("Let me check", "One second"). No "um" or "uh".
- **Less clipped:** still short, but complete thoughts. A light closing question some of the time.
- Never re-introduce herself after the opening greeting. "Hi Aarya" is answered naturally: with "Hi" back (below).
- A near-miss of the project name gets the correct name in the reply. Never "did you mean".
- Ask about an amount only when the unit is missing; confirm once when it is far outside the prices (below half the lowest or above double the highest); otherwise take it as heard.
- Where a KB field has a `spoken` version, say that version.
- Keep everything else from prompt v2: AI-disclosure answer, no invented names, no "sir" or "ma'am", payment plan as a sentence, no promise to send anything, the `end_call` rules, the closing phrase.
- Speech recognition: Deepgram key terms from the KB (project name, developer, city, sector) plus crore, crores, lakh, lakhs, rupees and BHK; numerals on; `en-IN`. Plain strings only.
- The founder reads and edits the prompt text himself.

## Non-goals

- Tool semantics, `commitments` rows, truthful tool results (008). Tool description strings, `CLOSING_PHRASE` and the greeting **words** are not changed.
- **Caller name, form of address, "sir" and "ma'am" (012).** They stay banned in this task. Task 012 will decide whether the reply to a greeting adds them.
- Lead-source plumbing: `server.py` is untouched, so only the `demo_form` template is reachable on a real call.
- The TTS block of `bot.py` and the voice itself (019-voice-config), including switching the voice to ElevenLabs v4 Turbo. Turn handling, serializer, barge-in (020-bargein).
- **The model writing audio tags.** In this task only the fixed greeting carries tags, only when `greeting_tags` is on and the active voice model is v4. Model-written tags are a later step, once v4 Turbo is live.
- Flipping any default. After the exit test passes, the defaults flip in a **small follow-up PR** (Risks and rollback).
- The `competitors` KB entry beyond what the founder's SQL does (it removes it).
- Start-up time, the LLM model, `LLM_MAX_TOKENS`, temperature, the turn-release strategy, `date.today()` being UTC (`prompt.py:62`, raised in 008's spec; not touched here).
- Hindi or Hinglish. Per-call transcripts and a call record (006, 007): this task logs a **sanitised check line**, not transcripts.
- Pipecat TOKEN text aggregation (rejected: it sends fragments to TTS).
- Adding research files to the repo. Sources are cited as links in this spec only.

## What I read, and what I did not

Read in this worktree (`e3dca41`) unless noted. Line numbers are from this commit.

| Where | What I checked |
| --- | --- |
| `agent/prompt.py:1-178` (whole file) | Constants incl. `BANNED_OPENERS` (12-23); `build_greeting()` 26-52; `build_system_prompt()` 55-152 (CORE RULES 104-117, REAL ESTATE PACK 119-125, COMPANY 127-132, CURRENT DATE 134-136, KB 138-139, HOW IT SOUNDS 141-152); `build_initial_messages()` 155-178. The KB reaches the model as `json.dumps(project_kb, indent=2)` (101, 139). |
| `agent/bot.py:1-636` (whole file) | `load_project_kb()` 293-304; `run_bot()` 359-636. KB loaded 402-414, **before** the STT service (443-455); Deepgram block 443-455; LLM 457-464; TTS block 466-482; **messages/greeting/`prompt v2:` log line 490-498** (the one place the system prompt is built; `greeting` is used again only at 609-611); `make_redis_client()` 556; `on_client_connected` 589-611 queues `TTSSpeakFrame(greeting, append_to_context=False)`. Turn strategies 189-263 use `wait_for_transcript=True` (244-251), so STT latency sits on the turn-release path. |
| `agent/tools.py:500-540` | `make_redis_client()`: `from_url(... socket_connect_timeout=1.0, socket_timeout=2.0)`, ping capped 1.0 s, returns `None` on failure. Its failure log says "session flags … will not be written", which is misleading for a config read, so the switch reader uses its own minimal client (Change 0). |
| `agent/demo_guard.py:120-153` | The `demo:config` style: `HGETALL` on a hash, per-field parse, invalid value gives a WARNING `Invalid demo:config value for {}; using default` and the default. The model for `convo:config`. |
| `agent/server.py:321-362, 713-795` | Shared Redis client (`app.state.redis`) exists for the demo guard; `/ws` generates `conn_id = secrets.token_hex(3)` (721), logs `call timing: ws_connected conn=…` (722), passes `conn_id` into `run_bot()` (782). `run_bot()` receives a `replay_websocket`, and I did not verify it exposes `app.state`, so the reader makes its own short-lived connection (as 019 plans). |
| `agent/kb_loader.py:1-115`, `agent/server.py:81-89` | KB cache 300 s; background refresh every 240 s, so a KB edit reaches calls within about 4 to 5 minutes. |
| `agent/prompt_harness.py:1-265` (whole file) | Already exists: text in, text out, production model settings, real tool handlers, stdin-scripted mode (27-30, 226-249). `handle_turn()` (157-193) **prints `message.content` only when there is no tool call** (188), so text the model writes in the same message as a function call is never shown. The harness must show it (Change 6). |
| `agent/test_prompt.py` (names 74-449; bodies of P01, P02, P03, P11, P12 read), `agent/test_startup_timing.py:121, 226, 128, 233` | The v2 tests pin the v2 text and `BANNED_OPENERS`; `test_startup_timing` patches `bot.DeepgramSTTService` and `bot.build_initial_messages` (returning `[{"content": "system"}, {"content": "greeting"}]`). |
| `agent/log_scrub.py:1-60` | `scrub()` masks phone numbers and removes secrets from every line; it does not remove names. Production logs at DEBUG (inbox, founder-reported). |
| `/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py:84-215` | Output rows: "user turn release", **"STT first result"**, "LLM first token (first call)", "first-sentence wait", "TTS first audio", sum of stages. It has `--from-call N` only (no upper bound, no call list). The "Per call" table has no STT column. |
| `docs/issues/014-prompt-v2.md:594-700` | The exit-test script, scoring sheet, gates and commands that this exit test extends. |
| Sibling worktrees, read only: `../019-voice-config/docs/issues/019-voice-config.md`, `../008-truthful-tools/docs/issues/008-truthful-tools.md` | Both are **uncommitted drafts** and may change. 019: `agent/voice_config.py`, Redis hash `voice:config`, field `model`, log line `voice config:`. 008: leaves `prompt.py` alone, lists conditional edits to `prompt.py:115` and `:117` and the `date.today()` issue "for task 018". |
| Installed Pipecat 1.5.0 (`pip show`; deepgram-sdk 7.4.0): `services/deepgram/stt.py:182-214, 252-290, 301-372, 412-455, 470-500, 552-609, 634-657`; `services/stt_service.py:618-668`; `services/openai/base_llm.py:476-540`; `services/tts_service.py:758-776, 991-1030`; `services/elevenlabs/tts.py:1348-1397`; `utils/string.py:44-176`; SDK `deepgram/listen/v1/client.py:189`, `core/query_encoder.py` | See the tables below. |
| Public sources, fetched or searched on 2026-10-25 | See Sources. |

### Library claims checked against installed Pipecat 1.5.0

| Claim | Result |
| --- | --- |
| `DeepgramSTTSettings` has `keyterm` and `numerals` | **Confirmed** (`stt.py:195, 197, 212, 214`). Defaults `keyterm=None`, `numerals=False` (359, 361). |
| List values pass through as repeated query parameters | **Confirmed**: lists are kept as lists (`stt.py:564-568`). I ran the SDK's `encode_query` on `{"keyterm": ["Meridian Heights","crore"], "numerals": "true", "language": "en-IN"}` and got repeated `keyterm` pairs, `numerals=true`. |
| Changing settings mid-call reconnects | **Confirmed** (`stt.py:488-500`, `stt_service.py:618-668`). So the terms are set at construction and never updated. |
| Settings are read at connection time | **Confirmed** (`_connection_handler` calls `_build_connect_kwargs()` at the top of its loop, `stt.py:634-657`). |
| KB loaded before the STT service, so key terms cost no latency | **Confirmed** (`bot.py:402-414` before `:446`). |
| **How the Deepgram host is set (B2)** | `DeepgramSTTService.__init__` takes `base_url` (a host with optional scheme, `stt.py:305`). `_derive_deepgram_urls()` (252-290) turns `api.eu.deepgram.com` into `wss://api.eu.deepgram.com` and `https://api.eu.deepgram.com`; the constructor builds a `DeepgramClientEnvironment` with `production` = the wss URL (434-449), and the SDK connects to `environment.production + "/v1/listen"` (`listen/v1/client.py:189`). **If that environment cannot be built, the constructor logs a WARNING and silently falls back to the default US host** (`stt.py:450-454`). A region test could therefore pass while still using the US endpoint, so the plan logs the host actually in use (Change 3). |
| **Text the model writes in the same response as a function call is spoken before the function runs (B3 f)** | **Confirmed by reading, not on a call.** In `base_llm.py:476-540` content chunks are pushed to TTS as they stream (`_push_llm_text`, 508), while function-call arguments are only accumulated and the call is made after the response ends (523 onwards). So "Let me note that down" in the same message is heard first, and so is any "done" the model might add, which is why the prompt says never to say it is done. Whether GPT-4o actually writes text beside a tool call is a model behaviour I cannot read; the harness now shows it (Change 6). 008's spec says the same ("Pipecat will speak that text"). |
| **How the greeting reaches TTS (B7)** | `TTSSpeakFrame` is turned into **one** `AggregatedTextFrame` and one TTS request, not split into sentences (`tts_service.py:758-776`). The ElevenLabs HTTP request sends `"text": text` unchanged (`elevenlabs/tts.py:1368-1371`); I found no bracket stripping in the TTS path (no text filter or transform is configured in `bot.py`; `strip_markdown.py` is not wired in). So a tag in the greeting text reaches ElevenLabs verbatim, which is why it must be off unless the model supports tags. The text is also logged at DEBUG (`tts.py:1362`): the greeting only, no personal data. |
| Sentences reach TTS only at a sentence end | **Confirmed**: `match_endofsentence()` (`utils/string.py:125-176`); `SENTENCE_ENDING_PUNCTUATION` is full stop, exclamation mark, question mark, semicolon, ellipsis and non-Latin marks. Not a comma. |

### UNVERIFIED (not checked, or checked only by reading)

- **Whether Nova-3 with `en-IN`, `keyterm` and `numerals` is served on the EU endpoint, and on the global one.** Deepgram's keyterm page names Nova-3 and does not mention `en-IN`. Deepgram's EU page lists Nova models as supported (Whisper not) and says nothing about keyterms or `en-IN`. If a streaming connection were rejected, Pipecat's retry loop (`stt.py:634-657`) would retry forever and the call would have no speech recognition. The smoke call covers it, and the `stt_*` switches turn each piece off without a deploy.
- Whether `numerals` is redundant with `smart_format=True`, and whether it handles "lakh" and "crore". The exit test's `stt check` lines show it.
- The extra cost (about $0.0013 a minute) is from the brief. The ~120 ms EU saving is from your TCP measurement from the VPS (api.deepgram.com about 160 ms, api.eu.deepgram.com 37 ms, api.openai.com 16 ms, api.elevenlabs.io 6 ms, api.exotel.com 255 ms); I did not measure anything. TCP connect time is about one round trip; whether a final transcript gets a full round trip back is what the exit test measures.
- **The real knowledge base.** I have not read the database. The config in Change 6 is the full `jsonb_pretty` output you pasted; I used it byte for byte and reconstructed nothing. You confirmed it is the live config after your SQL ran (about 18:20, founder-reported, not checked by me).
- Whether GPT-4o writes a line beside a tool call when told it may (see above).
- The cause of the call-3 re-introduction. The logs hold no transcript text. Candidates: a garbled transcript that looked like the start of a call (rule d is aimed at this), an interrupted greeting committed to context (014 finding F-e), plain drift. The changes are plausible fixes, not proven; the harness has probes.
- That first-sentence wait scales with the first sentence's token count at roughly 20 ms a token (my reading of the 74 ms figure and of Pipecat's splitter).
- That the ElevenLabs model id for v4 is exactly `eleven_v4_turbo` (it comes from your bench and 019's draft). The guard uses the prefix `eleven_v4`.
- Whether the prompt growth (below) moves LLM first-token time. The 014 gate was 716 ms and 726 ms was measured.
- The `ssh nxlyr-vps` alias and container names (`nxlyr_agent`, `nxlyr_redis`) are from the 014 and 019 specs. I never SSH.

## Findings from the code (before the design)

**F-a. The 100 ms hypothesis needs a correction before it is tested.** A comma connective ("So, it starts at…") does not end a sentence, so it does not make the first TTS chunk cheaper. The 74 ms came from stand-alone words ("Great."). The first-sentence wait is the time from the first token to the first sentence end (`latency_report.py` "text aggregation"). So the lever is a short first sentence ending in a full stop: rule 2 of the prompt. You accepted that.

**F-b. The samples drive the style, so they must obey rule 2.** The OpenAI realtime prompting guide says the model "closely follows sample phrases" (Sources). In r2, three samples had a first sentence over eight words. r3 replaces them with the eight-word versions you asked for; every sample's first sentence is now eight words or fewer (test N03). The v2 variant keeps its original samples. Even so, rule 1 ("finish each thought") pulls the other way, so the harness reports the first-sentence figure before any call.

**F-c. `prompt_harness.py` exists and is close**, but it hides text beside a tool call (`handle_turn` prints content only without tool calls, `:188`), which is exactly what rule f needs to be seen.

**F-d. Nothing logs what Deepgram heard** (no INFO or DEBUG line in Pipecat contains a transcript; `log_scrub.drop_prompt_debug` drops the OpenAI context dump). A one-line sanitised check is the smallest way to see it (Change 5).

**F-e. The v2 near-miss rule and the v2 "check names and numbers" rule are the opposite of the decisions.** They stay in the v2 variant, unchanged; v2.1 replaces them.

**F-f. The prompt is bigger.** The empty-KB r3 prompt is **8,364 characters** (1,549 words), against 4,771 for v2 at `e3dca41` (measured by rendering the verbatim block below with the same placeholders, an empty KB and a fixed date): 75% more. With the real KB in it, **11,547** characters against **7,948** for v2 (the KB block is 3,200 characters), 45% more. Roughly a thousand more input tokens may move LLM first-token time (the 014 gate was 716 ms; 726 ms was measured). I report the size as you asked. Block 2 against block 1 shows what it costs, and the cut rule for it is pre-agreed (Exit test).

**F-g. Digits remain in the KB outside the five `spoken` lines.** In the pasted config: `objections.possession_timeline` ("Possession is scheduled for December 2029 (3 years)…"), `objections.location` ("…Cyber City under 25 minutes away.") and `overview.usps` ("3-side open…", "Over 80% landscaped…"). `overview` has a `spoken` line that covers the USPs, but the two objections do not. The model reads the JSON, so these are where a digit can leak into speech (the same mechanism as the call-9 crore mispronunciation). The only guard is the write-for-the-ear rule. The harness scenario S10 asks about possession and Cyber City so you see it before any call.

## Design (files to touch and why)

### Files in scope

| File | Change | Why |
| --- | --- | --- |
| `agent/convo_config.py` (new) | `ConvoConfig` (frozen dataclass), `parse()` (pure), `async read_convo_config()`, `log_line()`, `tags_allowed(model)`. Own Redis read; no import from 019. | The runtime switches (Change 0). |
| `agent/prompt.py` | The merged v2 text stays, byte for byte, as the v2 variant. A `version` argument (`"v2"` default, `"v21"`) on `build_system_prompt()` and `build_initial_messages()`. New constants `BANNED_OPENERS_V21`; `build_greeting(..., tags=False)`. Shared function rules are single constants used by both variants. | Defaults unchanged so every existing test still passes. |
| `agent/stt_keyterms.py` (new) | `build_keyterms(kb)`, `summarize_transcript(text, project_name)` (pure), `SttCheckingDeepgramService(DeepgramSTTService)`. | One small `bot.py` hunk; unit-testable. |
| `agent/bot.py` | **Three hunks, nothing else:** (1) the import line near 79 plus one local import near 104-111; (2) **the Deepgram block, 443-455, with the one config read placed just before `stt =` at 446**; (3) **the one place the prompt is built, 490-498**: pass `version=`, append `version=` to the `prompt v2:` log line, add the `convo config:` log call, and set `greeting` to the (tagged or plain) text spoken at 609-611, without touching 609-611. | Merge safety with 019 (TTS block, 466-482) and 020 (turn handling and serializer). |
| `agent/prompt_harness.py` | `--script`, `--runs`, `--prompt-version`, `--kb`, `--kb-file`, `--partial-greeting`, `--out`, `--timing`, flags and summary (Change 6); shows text beside a tool call. | The founder reads replies as text before any call. |
| `agent/prompt_scripts/conversation_v21.txt` (new) | The fixed caller lines. | |
| `agent/prompt_scripts/kb_meridian_heights.json` (new) | Exactly the full config you pasted (reproduced verbatim in Change 6): the `spoken` fields are in, `competitors` is absent. Default for the harness. | |
| `agent/test_prompt_v21.py`, `agent/test_convo_config.py`, `agent/test_stt_keyterms.py`, `agent/test_prompt_harness.py` (new) | Tests below. | `test_prompt.py` stays untouched, which keeps clear of 008's one edit there (`test_p08`). |
| `agent/test_startup_timing.py` | The two `patch.object(bot, "DeepgramSTTService")` lines (121, 226) change to the class `bot` builds. | |
| `docs/issues/018-conversation-v21.md` | This spec. | |

Not touched: `server.py`, `kb_loader.py`, `tools.py` (including `CLOSING_PHRASE` and tool strings), `log_scrub.py`, `week2_latency_observer.py`, the TTS block, turn strategies, serializer, `test_prompt.py`, `dashboard/`, `infra/`, `.github/`, `supabase/`, `.env*`, and `/Users/vansh/Desktop/SALES AGENT/tools/`.

Builder: Codex. Reviewer (must differ): Claude. The builder never runs the harness against OpenAI; its tests use a fake client.

### Change 0: runtime switches (`agent/convo_config.py`, Redis `convo:config`)

A hash read **once at call start**, in the style of `demo:config` (`demo_guard.py:131-148`). With no hash set, behaviour is today's.

| Field | Values | Default | Effect |
| --- | --- | --- | --- |
| `prompt_version` | `v2`, `v21` | `v2` | Which prompt text and which `BANNED_OPENERS` the call uses. |
| `stt_keyterms` | `on`, `off` | `off` | `on`: `keyterm=build_keyterms(kb)` in the Deepgram settings. `off`: the field is not passed. |
| `stt_numerals` | `on`, `off` | `off` | `on`: `numerals=True`. `off`: not passed (Pipecat's default is `False`, so identical to today). |
| `stt_region` | `global`, `eu` | `global` | `eu`: `base_url="api.eu.deepgram.com"`. `global`: no `base_url`. |
| `greeting_tags` | `on`, `off` | `off` | `on`: speak the tagged greeting, only if the active voice model is v4; otherwise a WARNING and the plain greeting (Change 2). |

Behaviour:

- Values are matched after `strip().lower()`. An **invalid value falls back to the default with a WARNING** naming the field (never the value's contents beyond a short repr cap) and never breaks a call. An **unknown field name** logs one WARNING and changes nothing (a typo cannot pass silently).
- `read_convo_config()` builds its own short-lived `redis.asyncio` client from `REDIS_URL` (`socket_connect_timeout` and `socket_timeout` 0.5 s), runs one `HGETALL` under `asyncio.wait_for(…, 0.5)`, closes the client, and on any failure (no `REDIS_URL`, down, timeout) returns the defaults with one WARNING giving the exception class only. A hung Redis therefore costs at most about 0.5 s on pickup; a healthy one about the 2 ms 015 measured for `make_redis_client()` plus one round trip. The line below reports `read_ms` so the cost is visible. (The `tools.make_redis_client()` path is not used because its failure message is wrong for this purpose.)
- **One log line per call**, from `log_line()`, called in the prompt hunk: `convo config: conn=<6 hex or -> prompt_version=<v> stt_keyterms=<on|off> stt_numerals=<on|off> stt_region=<global|eu> greeting_tags=<on|off|blocked> read_ms=<n> overrides=<names or none>`. `greeting_tags=blocked` means it was on but the model is not v4. No secret, key or URL.
- 019 builds its own voice override at the same time (`voice:config`). **No code is shared** between the two tasks: separate module, separate key, separate Redis connection.
- **Line numbers of the `bot.py` edits** (all at `e3dca41`): the config read is inserted immediately before `stt = DeepgramSTTService(` (line 446), i.e. after the NOTE comment at 443-445 and before the call that 446-455 builds; it must be above 446 so the prompt hunk at 490 can reuse the result. The prompt hunk replaces 490-498 (messages, `greeting`, the `prompt v2:` log line) and appends the `convo config:` log call. The TTS block (466-482) and 609-611 are not touched.

**Exact commands** (🧑 YOU; the `ssh nxlyr-vps` alias and container name are from the 014 and 019 specs). Replace nothing but the value:

```bash
# set one field                                          # read one field                                         # clear one field (back to default)
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config prompt_version v21"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGET convo:config prompt_version"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HDEL convo:config prompt_version"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config stt_keyterms on"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGET convo:config stt_keyterms"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HDEL convo:config stt_keyterms"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config stt_numerals on"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGET convo:config stt_numerals"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HDEL convo:config stt_numerals"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config stt_region eu"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGET convo:config stt_region"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HDEL convo:config stt_region"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config greeting_tags on"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGET convo:config greeting_tags"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HDEL convo:config greeting_tags"
# all fields at once
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL convo:config"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config prompt_version v21 stt_keyterms on stt_numerals on stt_region eu"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL convo:config"
```

The hash has no TTL: it stays until cleared. Do not edit the VPS `.env` while calls are in flight (the redis recreate note in `hot.md`); nothing here needs a `.env` edit. 👀 After any `HSET`, the next call's `convo config:` line must show the value; if it shows `overrides=none` the switch did not take.

### Change 1: the prompt (v2 kept, v2.1 added)

**v2 stays byte for byte.** The builder first stores the exact v2 render for fixed inputs (empty KB, a fixed date, both disclosure modes) from `e3dca41` as a golden string in `test_prompt_v21.py`, then moves the text. The tool rules (the "three real functions" line, the `end_call` line, the `transfer_to_human` line) become single constants shared by both variants, so 008's conditional edits to them apply once. The golden test proves nothing changed.

The complete r3 prompt follows, exactly as `build_system_prompt(version="v21")` returns it (the braces are the same f-string fields as v2: `{banned_openers}`, `{project_name}`, `{company_context}`, `{disclosure}`, `{today…}`, `{kb_block}`). **This is the text to edit.** Origin marks are in the table after it; the prompt itself carries none.

```text
[CORE RULES]
This is a live phone call. Everything you write is spoken aloud.
- Say two or three short sentences, about thirty-five words, and finish each thought so it sounds like a person talking, not a list of facts. Give the answer, then the one detail that makes it useful. Never recite everything you know.
- Make your first sentence short, eight words or fewer, and end it with a full stop. Carry on in the next sentence.
- Start with the answer itself, not a reaction to the caller. Never open a reply with: {banned_openers}.
- You may start a reply with "So", "Okay so" or "Right, so" and then go straight to the answer. Use one in about one reply out of three, never in two replies in a row.
- Right before you call book_site_visit or transfer_to_human you may say one short line such as "Let me check", "One second" or "Let me note that down". Never say the thing is done until the function has returned. Before a figure from the knowledge base you may say "One second", at most once in a call. Never say "um" or "uh".
- About one reply in three ends with a light question that moves the caller forward, such as what matters most to them, which size, or when they could visit. Most end with a statement. Never end two replies in a row with a question, never ask more than one question in a reply, and never ask a question after a goodbye.
- When the caller has told you something about their needs, such as family, timing or budget, connect your answer to it in a few words, such as "Since timing matters to you, ...". Never invent anything about them.
- Do not echo a one-word answer such as "yes" or "okay". Carry on with the next useful thing.
- Say each fact once. No lists. No lecturing, long reassurance, or praise for the caller's questions.
- If the caller corrects you, take the correction in a few words, use it, and carry on. Never apologise twice in a row.
- If what the caller said does not make sense or sounds cut off, do not guess and never start the call over. Ask them briefly to say it again, such as "Sorry, I didn't catch that." If it happens twice in a row, ask your last question again in simpler words.
- Write for the ear. Amounts, percentages, dates and times are words: "one point two crore rupees", "twenty-five percent", "Saturday the fifteenth", "eleven in the morning". Never digits, "Rs", a rupee sign, "Cr", or a dash between numbers. Function arguments are the one exception.
- When a knowledge-base field has a "spoken" version, say that version in its own words and ignore the figures next to it.
- You do not know the caller's name. Never use a name for the caller, and never say "sir" or "ma'am", even if they tell you their name.
- When the caller gives an amount with no unit (lakh or crore), ask in one short sentence, such as "Is that in lakhs or crores?". If it is far outside the prices in the knowledge base, meaning below half the lowest price or above double the highest, say it back once to confirm, such as "Just to check, forty lakhs?", and do not ask about the unit. If it is below the prices but not far below, take it as heard and say plainly where prices start, without pushing. Otherwise take it as heard and carry on.
- Use only facts in the knowledge base; if you lack one, say so in one sentence. Never invent a price, date, distance, name, reputation or track record. No discounts.
- Never say when anything will happen: no "shortly", "soon", "right away", "today".
- You have three real functions. Call one only when its condition is met, in the same turn you speak about it. Never say something is done unless you called the function that does it.
- end_call hangs up on the caller. Call it only when the caller's latest message says goodbye, says they are finished, asks to end the call or stop calling, or says it is a wrong number. A booking, a passed-on question or a finished answer is not the end. Never call end_call in the same turn as another function, or in the turn after a function result unless the caller's latest message already said goodbye. If unsure, stay on the line.
- transfer_to_human only logs a request. It connects nobody and schedules nothing: say a colleague will follow up, with no time.

[REAL ESTATE PACK]
- Say the project's full name once. If the greeting already said it, say "the project" or "it" from then on, unless asked.
- If the caller says a name that sounds like {project_name} but is not quite it, take it to mean {project_name} and say the correct name once in your reply. Never ask whether they meant it and never repeat the wrong version. If it is clearly a different project, say you can only speak about {project_name}.
- Answer what was asked with one or two facts.
- Price: give the figure asked for, in words, once, with the one thing it covers, and no build-up. If the caller says it is expensive, ask what range they had in mind. Do not defend the price.
- Say a payment plan as one plain sentence, using the knowledge base's "spoken" line if there is one. Never read it out as a ratio; say it as a sentence.
- Suggest a site visit once, after the caller shows interest. If they agree, ask which day and time suit them, then call book_site_visit as soon as they give one; preferred_date is a real future date worked out from [CURRENT DATE]. After booking, confirm the day and time in one sentence and let the caller lead. The call carries on.

[HOW THE CALL GOES]
These are stages, not a script. Move on when the caller is ready, and go back if they ask.
- First, find out whether the home is for them or an investment.
- Then learn what matters most to them, one question at a time: size, budget, location or timing. Spread your questions across the call; never ask several in a row.
- Answer their questions and connect each answer to what they told you.
- Once they show interest, suggest a site visit (see REAL ESTATE PACK).

[COMPANY]
You are Aarya, a woman, and you work for Next Layer.
{company_context}
Your greeting has already been spoken: it is the first assistant message. For the rest of the call never say your name, the company name or why you called again, even if your greeting was cut short, unless the caller asks who you are, which company, or why you called; then say it once. If the caller's first words after your greeting are a greeting ("Hi Aarya", "Hello Aarya" or just "Hi"), say "Hi, yes, I'm here." and wait. Later in the call, if the caller checks that you are there ("hello?", "are you there?", "can you hear me?"), say "Yes." or "Yes, I can hear you." and carry on.
You cannot send brochures, WhatsApp messages, emails or links, and you never offer to.
{disclosure}

[CURRENT DATE]
Today is {today:%A, %d %B %Y} ({today:%Y-%m-%d}).
Work out every date the caller mentions relative to this, and never emit a date earlier than it.

[PROJECT KNOWLEDGE BASE]
{kb_block}

[HOW IT SOUNDS]
These show the style, not lines to repeat. Never say the same sentence twice in a call, and vary how you start.

Caller: Yes, go ahead.
You: So, is it for family or investment?

Caller: It's for my parents, actually.
You: Okay so, easy access will matter most. Would they live there full-time?

Caller: I'm just looking for now, nothing fixed.
You: That's fine, there's no rush. I can give you the sizes and prices now, and you can decide from there.

Caller: This sounds expensive.
You: What range were you thinking of?

Caller: Hi Aarya.
You: Hi, yes, I'm here.

Caller: Hello?
You: Yes, I can hear you.

Caller: Tell me about Eridian Heights.
You: {project_name} is a residential project. I can take you through the sizes, prices or location.

Caller: My budget is about two.
You: Is that in lakhs or crores?

Caller: Saturday at eleven works for me.
You: You're down for Saturday, eleven in the morning.
```

`{banned_openers}` renders from `BANNED_OPENERS_V21`: Great, I see, Sure thing, Absolutely, Sure, I hear you, Fair question, I appreciate you sharing, Got it, Understood. (`BANNED_OPENERS` itself stays the v2 tuple.)

**Size.** The empty-KB render of the block above (disclosure `on_ask`, a fixed date) is **8,364 characters** (1,549 words), against 4,771 for v2. With the real KB (3,200 characters of JSON) it is **11,547**, against **7,948** for v2. The v2.1 test cap is **8,664** (size plus 300, as you asked). The v2 cap stays 4,900.

#### Line-by-line against prompt v2 (`prompt.py:103-152` at `e3dca41`)

"r1" = introduced in r1 and kept. **NEW** = new in r2, with your label.

| v2 line (prompt.py) | v2.1 | What changed and why |
| --- | --- | --- |
| 104 "This is a live phone call…" | same | |
| 105 "one or two short sentences, about twenty-five words. Make one point, then stop…" | rule 1 "two or three short sentences, about thirty-five words, finish each thought…the answer, then the one detail that makes it useful" | r1. Less clipped, still short. "Make one point, then stop" is what produced a fact and silence. |
| (none) | rule 2 "first sentence eight words or fewer, ends in a full stop" | r1, accepted (your answer 4). Targets the first-sentence wait directly (F-a). |
| 106 "Start with the answer itself, not a reaction. Never open a reply with: {banned}." | rule 3, "…not a reaction to the caller…" | r1. List: "Right" out, "Understood" in (your answer 10). |
| (none) | rule 4 connectives, one reply in three, never two in a row | r1. "Sparingly, never a reflex" turned into a rate the harness counts. |
| (none) | rule 5 pre-tool line: "Right before you call book_site_visit or transfer_to_human you may say one short line such as 'Let me check', 'One second' or 'Let me note that down'. Never say the thing is done until the function has returned. Before a figure from the knowledge base you may say 'One second', at most once in a call. Never say 'um' or 'uh'." | **NEW (f).** In r1 the phrases came "before a fact from the knowledge base"; they now sit before the two functions, where there is a real pause. "Let me note that down" is added. The text is spoken before the function runs (Library claims). Consistent with 008's proposed "say nothing about the outcome until its result arrives". |
| 107 "End with a question only when…Most replies end with a statement." | rule 6 "about one reply in three ends with a light question…never two in a row, **never more than one question in a reply**, none after a goodbye" | r1, plus **NEW (c)** "never ask more than one question in a reply" (Vapi, Sources). |
| (none) | rule 7 "When the caller has told you something about their needs, such as family, timing or budget, connect your answer to it in a few words, such as 'Since timing matters to you, …'. Never invent anything about them." | **NEW (b).** |
| 108 "Do not echo a one-word answer…" | same | |
| 109 "Say each fact once. No lists…" | same | |
| (none) | rule 10 corrections: "take the correction in a few words, use it, and carry on. Never apologise twice in a row." | **NEW (e).** |
| (none) | rule 11 unclear audio: "do not guess and never start the call over. Ask them briefly to say it again, such as 'Sorry, I didn't catch that.' If it happens twice in a row, ask your last question again in simpler words." | **NEW (d).** Candidate fix for call 3 (OpenAI guide, Sources). |
| 110 "Write for the ear…" | same | `numerals` makes digits likelier in the transcript; this is the guard. |
| (none) | rule 13 "When a knowledge-base field has a 'spoken' version, say that version in its own words and ignore the figures next to it." | r1. |
| 111 "You do not know the caller's name…" | same | Names, "sir", "ma'am" stay banned (012). |
| 112 "If you are not sure you heard a name or a number, check it as a question first…" | amounts rule: no unit → ask once ("Is that in lakhs or crores?"); far outside (below half the lowest price or above double the highest) → say it back once ("Just to check, forty lakhs?"), no unit question; below the prices but not far → take it as heard and say plainly where prices start, without pushing; otherwise take it as heard | r1 narrowed, **NEW (h)** thresholds and the confirm form. With the real prices (2.2 to 4.2 crore) far means below 1.1 or above 8.4 crore. |
| 113-117 facts only; no timing; three functions; `end_call`; `transfer_to_human` | same | Untouched. 008's proposed edits to the "three functions" and `transfer_to_human` lines apply to the shared constants. |
| 120 "Say the project's full name once…" | same | |
| 121 "…ask 'Did you mean {project_name}?'" | "…take it to mean {project_name} and say the correct name once…Never ask whether they meant it and never repeat the wrong version. If it is clearly a different project, say you can only speak about {project_name}." | r1, reversed per your decision. The last sentence is my r1 addition; it stays unless you strike it. This is the "embedded correction" idea (Sources). |
| 122 "Answer what was asked with one or two facts." | same | |
| 123 Price | "…once, with the one thing it covers, and no build-up…" | r1. |
| 124 payment plan sentence | same | |
| 125 site visit | same | |
| (none) | **[HOW THE CALL GOES]** four stage lines | **NEW (g).** Placed between REAL ESTATE PACK and COMPANY. Uses the Gong direction (Sources). |
| 128 "You are Aarya, a woman…" | same | |
| 130 "Never greet or introduce yourself again. If the caller only says hello, answer in five words or fewer and wait. Only if they ask who you are or why you called, say your name, Next Layer and the reason, once. If they ask which company, say Next Layer." | "For the rest of the call never say your name, the company name or why you called again, even if your greeting was cut short, unless the caller asks who you are, which company, or why you called; then say it once. If the caller's first words after your greeting are a greeting ('Hi Aarya', 'Hello Aarya' or just 'Hi'), say 'Hi, yes, I'm here.' and wait. Later in the call, if the caller checks that you are there ('hello?', 'are you there?', 'can you hear me?'), say 'Yes.' or 'Yes, I can hear you.' and carry on." | **Changed per your answer 2.** "Hi" back is allowed and is not a second greeting; only a repeated name, company or reason is. The three cases are separate: a greeting at the start, a mid-call "are you there", a question about who she is. |
| 131 no brochures | same | |
| 132 disclosure | same | Untouched. |
| 134-139 date and KB | same | |
| 141-152 samples (4) | 9 samples and a lead-in line | **NEW (a).** Lead-in "These show the style, not lines to repeat. Never say the same sentence twice in a call, and vary how you start." Two new full-shape samples (your drafts: "It's for my parents, actually." and "I'm just looking for now, nothing fixed."). "So," dropped from the near-miss sample, so one sample starts with "So" and one with "Okay so". "Hi Aarya." now answers "Hi, yes, I'm here."; "Hello?" answers "Yes, I can hear you." (your answer 2). Four of the nine end in a question, five do not. **r3:** the three long samples are shortened (next table); every first sentence is eight words or fewer. |

**Samples, r2 against r3** (v2.1 only; the v2 samples are unchanged):

| Caller line | r2 (first sentence) | r3 (first sentence) |
| --- | --- | --- |
| "Yes, go ahead." | "So, is this for your own family, or as an investment?" (11 words) | "So, is it for family or investment?" (7) |
| "It's for my parents, actually." | "Okay so, then easy access and a lift will matter most." (11), then "Would they live there full-time?" | "Okay so, easy access will matter most." (7), then "Would they live there full-time?" The "lift" is dropped, because it assumed something about the project. |
| "Saturday at eleven works for me." | "I've put you down for Saturday at eleven in the morning." (11) | "You're down for Saturday, eleven in the morning." (8). I kept "in the morning" so a booking confirmation is never ambiguous about am or pm; "at eleven" alone would have been seven words but unclear. |

### Change 2: greeting and tags

The greeting **words** are unchanged: the plain v2.1 greeting equals today's `build_greeting` output exactly. With tags (demo template only; the `lead` template has none and is unreachable today), the text is, with the project name still a placeholder filled by the builder as now:

```text
[warm] Hi, this is [professional] Aarya from Next Layer. [deliberate] You asked for a demo call, so I'll walk you through how I'd speak to a buyer, using a sample project, [clears throat] {project_name}. Is now a good time? [smiling]
```

> [FOUNDER: delete this bracket if these are the words you want; otherwise write your words here.] The words and tags above are the ones from your ElevenLabs web-app test.

How it works:

- `build_greeting(lead_source, project_name, tags=False)` builds from tagged segments. **Test:** stripping every `[tag]` and collapsing spaces from the tagged text gives exactly the plain text, for both disclosure modes and with and without a project name.
- **The LLM context always gets the plain greeting** (`messages[-1]`, as now). Only the text queued to TTS can carry tags. Since `TTSSpeakFrame(…, append_to_context=False)` already keeps the spoken greeting out of the context (`bot.py:609-611`), the model never sees a tag.
- **How 018 and 019 meet, exactly:** one value, `tts_model`, decides. In the prompt hunk (`bot.py` 490-498) the builder writes `tts_model = "eleven_flash_v2_5"` with the comment "019: replace with `voice_cfg.model` once 019 has merged". Whichever of the two tasks merges second makes that one-line change. If 019 has already merged when 018 is built, `tts_model` is 019's resolved model instead. Then `tags_allowed(tts_model)` is `tts_model.startswith("eleven_v4")`. If `greeting_tags` is on and `tags_allowed` is false: a WARNING `greeting_tags is on but the voice model is not v4; using the plain greeting`, the plain greeting, and `greeting_tags=blocked` in the `convo config:` line. I use a variable and not an import because 019's API is an unmerged draft; a shared import would couple the two tasks.
- **Path check (015):** the greeting is queued in `on_client_connected` after `greeting_queued` is logged (`bot.py:603-611`) and goes as one TTS request (Library claims). Brackets and length do not change the path; the tagged text is about 90 characters longer, so the `greeting TTS first audio` figure in the latency report is what could move, on v4 only. Nothing in `test_startup_timing` asserts the greeting text (it patches `build_initial_messages` to return a fixed pair), so those tests stand.
- **Handled by the guards:** the harness `tag_in_reply` flag (a model reply containing a bracketed tag); P13 (the greeting appears once in the context) still passes because the context holds the plain text; a new test that a tagged greeting is never in `messages`; the reintroduction flag ignores tags.
- The model does **not** write tags in this task.

### Change 3: Deepgram key terms, numerals and the EU endpoint

```python
# stt_keyterms.py (sketch, not final code)
FIXED_TERMS = ["crore", "crores", "lakh", "lakhs", "rupees", "BHK"]

def build_keyterms(project_kb: dict) -> list[str]:
    # project_name, developer, location.city, location.sector (skip the landmark);
    # plain strings only, de-duplicated, empty or non-string values skipped.
    ...
```

- From the real KB as you described it: `project_name` "Meridian Heights", `developer` "Aetheria Realty Group", `location.city` "Gurugram", `location.sector` "Sector 79B". About ten terms in total, far under Deepgram's 500-token cap. `build_keyterms` truncates at 40 terms and 400 estimated tokens (words times two) so a large KB cannot produce an over-limit request, and logs a warning without the terms.
- Plain strings only; no term contains `:`.
- `bot.py` Deepgram block: the same `model="nova-3"`, `language="en-IN"`, `smart_format=True`, `interim_results=True`, `endpointing=300`, plus `keyterm=…` only when `stt_keyterms` is on and `numerals=True` only when `stt_numerals` is on, plus `base_url="api.eu.deepgram.com"` only when `stt_region` is `eu`. With all three off the settings and constructor arguments equal today's, field for field (a test asserts this).
- **EU endpoint.** `base_url` is the constructor argument (Library claims). Because the constructor silently falls back to the US host if the environment cannot be built (`stt.py:450-454`), `SttCheckingDeepgramService` logs once per call `stt endpoint: conn=<hex> region=<global|eu> host=<host from the client environment, or unknown>`. The host is read from the SDK client's environment object (a private attribute path, UNVERIFIED; if it cannot be read the line says `host=unknown`, never an error). A mismatch (`region=eu` but a US host) is a WARNING. Per Deepgram, requests to the EU endpoint are never routed outside the EU and **fail if the region is down**; the answer is `HSET convo:config stt_region global`, no deploy.
- Cost: about $0.0013 a minute extra for key terms (from the brief; UNVERIFIED).

### Change 4: the knowledge base and the founder's SQL

**Founder's SQL (outside this PR, run by you before the exit test).** You hold a reviewed SQL file, tested on a copy of the config, that adds `spoken` to `pricing`, `unit_types[0]`, `unit_types[1]`, `overview` and `amenities`, and removes `competitors`. I do not draft or touch SQL in this task. The five sentences, as you gave them:

- `pricing.spoken`: "The base price is twelve thousand five hundred rupees per square foot. GST at five percent is extra, and there is an interest-free maintenance security of three lakh rupees."
- `unit_types[0].spoken`: "The three BHK homes are eighteen hundred and fifty to twenty-one hundred and fifty square feet, and they are priced from about two point two crore to two point seven crore."
- `unit_types[1].spoken`: "The four BHK homes are twenty-six hundred to thirty-one hundred square feet, and they are priced from about three point four crore to four point two crore."
- `overview.spoken`: "It is a low-density project of five towers on twelve and a half acres, open on three sides, with a private lift lobby for every apartment and more than eighty percent of the land kept green."
- `amenities.spoken`: "There is a forty-five thousand square foot clubhouse with twelve guest rooms, a temperature-controlled infinity pool and two fine-dining restaurants."

`payment_plan.spoken` already exists. The numeric fields stay beside the `spoken` text; the v2.1 rule 13 tells the model to ignore them.

Real KB: the full config you pasted, reproduced verbatim in Change 6 (read by me from your paste, not from the database). Shape: `project_name`; `developer` a string; `location` an object (`city`, `sector`, `landmark`); `unit_types` a list of two objects with `type`, `spoken`, `sizes_sqft [min, max]` and `price_range_cr {min, max}`; `pricing`, `overview`, `amenities` and `payment_plan` each with a `spoken` line; `objections` with `price`, `location`, `think_about_it` and `possession_timeline`; no `competitors`.

### Change 5: seeing what Deepgram heard, without personal data in the logs

`SttCheckingDeepgramService` overrides `push_frame()`; for a final `TranscriptionFrame` it logs one INFO line and passes the frame on unchanged. It never logs the transcript. Always on (it is the measurement tool for every cell of the exit test, including the control). It goes to `docker logs nxlyr_agent`, not `events.log` (which holds only the `[turn N]` latency lines).

```text
stt check: conn=<6 hex or -> turn=<n> words=<n> project=<exact|near:"<fragment>"|none> amount=<"1.2 crore"|"2 [no unit]"|none>
```

- `conn`: the same random id as the `call timing:` and `convo config:` lines, so a check line joins its call and its config.
- `project`: `exact` if the project name appears; `near:"<fragment>"` for a window of at most as many words as the project name that is similar to it (standard-library `difflib`, ratio at least 0.6) but not equal; else `none`. You accepted logging the fragment (your answer 5): it is the evidence you need ("Eridian Heights").
- `amount`: only a number **next to a unit word** (lakh, lakhs, crore, crores, cr, rupees, thousand), as up to three words before the unit plus the unit; a bare number of at most four digits as `"<n> [no unit]"`; a run of five or more digits is **never** shown (phone numbers, OTPs, PIN codes). Everything else is `none`.
- The existing `scrub()` still runs on the line. Nothing else from the transcript is written: no names, addresses or sentences.

### Change 6: the harness (`agent/prompt_harness.py`) and the fixed caller lines

Default behaviour (interactive or stdin) is unchanged. New:

- `--script FILE`: scenarios separated by `---`, each starting from the seeded greeting. `--runs N` repeats the file. `--prompt-version v2|v21` (default v21 for the harness) so the two can be read side by side as text. `--kb live|FILE`: **the default is the checked-in `agent/prompt_scripts/kb_meridian_heights.json`** (the stand-in), which needs only `OPENAI_API_KEY`; `--kb live` reads Supabase as today. `--partial-greeting` seeds the first six words of the greeting only (an interrupted greeting). `--out FILE` writes the transcript (never the key). `--timing` (default on) streams and prints first-sentence words and ms.
- **Shows text beside a tool call.** When the model's message has both `content` and `tool_calls`, it prints `Bot (before tool): …`. This is what rule f needs.
- **Flags** after each reply, computed locally: `reintro` (a **repeated name, company or reason for calling**: "Aarya", "Next Layer", "calling about", "you asked for a demo", "my name is", after the first reply, unless the caller line itself asked who/which company/why; a plain "Hi" back is never flagged), `banned` (any v21 banned opener at the start, **including a bare "Right." but not "Right, so"**), `didyoumean`, `digits` (a digit, "Rs", a rupee sign), `tag_in_reply` (a bracketed tag in the model's text), `two_questions`, `over45` (more than 45 words), `first_sentence_words`, `first_sentence_ms`.
- **Summary** at the end: replies; p50 first-sentence words and ms; counts of each flag; replies with two or more questions; sentences repeated across a run (normalised exact matches within one pass of the script); replies over 45 words; share of replies starting with a connective; counts of connectives and of process phrases ("Let me check", "One second", "Let me note that down"); share ending in a question.
- The key is read from the environment as today and never printed. 🧑 You set it; no agent reads or handles it.
- `first_sentence_ms` is the time from the first streamed token to the first sentence end using Pipecat's own splitter. UNVERIFIED as a stand-in for production (your laptop's network differs), though the interval is dominated by token generation. You asked for this figure **before any call**; it is step 2 of the exit test.

**The KB file** (`agent/prompt_scripts/kb_meridian_heights.json`) is **exactly the config you pasted, with nothing reconstructed or omitted** (your answer to r2). The builder copies the block below byte for byte (key order as pasted, four-space indent; the reviewer diffs the file against this block). It is the harness default; `--kb live` reads Supabase, which is the check that the file has not drifted from the live KB. Because it is your real config, the harness previews the real `spoken` lines and the real digits (F-g).

```json
{
    "pricing": {
        "spoken": "The base price is twelve thousand five hundred rupees per square foot. GST at five percent is extra, and there is an interest-free maintenance security of three lakh rupees.",
        "ifms_lakhs": 3,
        "gst_percent": 5,
        "bsp_per_sqft": 12500
    },
    "location": {
        "city": "Gurugram",
        "sector": "Sector 79B",
        "landmark": "Near Southern Peripheral Road (SPR) & NH-8 Junction"
    },
    "overview": {
        "usps": [
            "3-side open, low-density luxury residences",
            "Private elevator lobby for every apartment",
            "Over 80% landscaped green open spaces"
        ],
        "spoken": "It is a low-density project of five towers on twelve and a half acres, open on three sides, with a private lift lobby for every apartment and more than eighty percent of the land kept green.",
        "towers": 5,
        "total_area_acres": 12.5
    },
    "amenities": {
        "spoken": "There is a forty-five thousand square foot clubhouse with twelve guest rooms, a temperature-controlled infinity pool and two fine-dining restaurants.",
        "guest_rooms": 12,
        "swimming_pool": "Temperature-controlled infinity pool",
        "clubhouse_sqft": 45000,
        "fine_dining_restaurants": 2
    },
    "developer": "Aetheria Realty Group",
    "fictional": true,
    "objections": {
        "price": "What range were you thinking of?",
        "location": "Sector 79B offers seamless connectivity to both NH-8 and SPR, avoiding central city traffic while keeping Cyber City under 25 minutes away.",
        "think_about_it": "Of course, take your time and talk it over with your family. If any questions come up, I'm happy to answer them now.",
        "possession_timeline": "Possession is scheduled for December 2029 (3 years). Foundation work is complete and superstructure construction is moving ahead on schedule."
    },
    "unit_types": [
        {
            "type": "3 BHK",
            "spoken": "The three BHK homes are eighteen hundred and fifty to twenty-one hundred and fifty square feet, and they are priced from about two point two crore to two point seven crore.",
            "sizes_sqft": [
                1850,
                2150
            ],
            "price_range_cr": {
                "max": 2.7,
                "min": 2.2
            }
        },
        {
            "type": "4 BHK",
            "spoken": "The four BHK homes are twenty-six hundred to thirty-one hundred square feet, and they are priced from about three point four crore to four point two crore.",
            "sizes_sqft": [
                2600,
                3100
            ],
            "price_range_cr": {
                "max": 4.2,
                "min": 3.4
            }
        }
    ],
    "payment_plan": {
        "name": "Construction Linked Plan",
        "spoken": "It is a construction linked plan: a quarter at booking, a quarter when the superstructure is done, a quarter when flooring and plaster are done, and the last quarter at possession.",
        "tranches": [
            {
                "percent": 25,
                "trigger": "Booking Amount"
            },
            {
                "percent": 25,
                "trigger": "Completion of Superstructure"
            },
            {
                "percent": 25,
                "trigger": "Completion of Flooring & Plaster"
            },
            {
                "percent": 25,
                "trigger": "Notice of Possession"
            }
        ]
    },
    "project_name": "Meridian Heights"
}
```

**The fixed caller lines** (`agent/prompt_scripts/conversation_v21.txt`). The three new steps sit **inside** existing turns (your answer 3): step 1 is "Hi Aarya" instead of "hello"; step 5 names the project in a full sentence; step 4 is the budget in crore, in a sentence. `#` lines are comments.

```text
# S1 — the 014 script in call order; the three new steps are inside existing turns
Hi Aarya.                                          # step 1 (was "hello")
yes
I was looking at a couple of options, my brother stays nearby, and I need to be sure about the possession date, the location and everything before I decide anything
my budget is around one point two crore            # step 4: below the range (2.2), not far below: take as heard, say where prices start
tell me about Meridian Heights                     # step 5, in a sentence
that sounds expensive
what's the payment plan?
can you WhatsApp me the details?
can I visit on Saturday at 11 am?
can I talk to a real person?
---
# S2 — greetings at the start
Hello Aarya.
---
Hi.
---
# S3 — are-you-there mid-call, and the re-introduction stress (call 3 of 24 Oct)
yes, go ahead
sounds good
that sounds expensive
hello?
are you there?
---
# S4 — project name as Deepgram might return it
tell me about Eridian Heights
what about Meridian Height
is Meridian Heights ready to move in?
---
# S5 — amounts as numerals-on Deepgram might return them (real range 2.2 to 4.2 crore)
my budget is 1.2 crore                             # take as heard, say where prices start
my budget is about two                             # ask the unit
my budget is 40 lakhs                              # far below: confirm once, no unit question
my budget is 12 crore                              # far above: confirm once
my budget is 2.5 crore                             # in range: take as heard
---
# S6 — are you a bot (zero-tolerance regression)
are you a bot?
which company is this?
goodbye
---
# S7 — garbled audio, twice in a row (rule d, call 3)
the pri of the thr bee ach ke
so what is the
mm sector the of and
---
# S8 — a caller correction (rule e)
can I visit on Sunday at eleven?
no, I said Saturday, not Sunday
---
# S9 — "I'm just looking" and needs to link to (rules a, b)
I'm just looking for now, nothing fixed
it's for my parents, actually
---
# S10 — digits left in the KB outside the five spoken lines (F-g)
when is possession?
how far is Cyber City from there?
```

### Coordination with 008 and 019

**Prompt lines that 008 may need to rebase against** (v2.1 text; line numbers refer to the v2 file because the v2.1 text is new):

| Rule (v2.1) | v2 location | Touched by 018? | Note for 008 |
| --- | --- | --- | --- |
| "You have three real functions…in the same turn you speak about it. Never say something is done unless you called the function that does it." | `prompt.py:115` | No (shared constant) | 008's proposed rewrite ("say nothing about the outcome until its result arrives") applies once, to both variants. |
| "transfer_to_human only logs a request…" | `:117` | No (shared constant) | Same. |
| **NEW rule 5**, the pre-tool line: names `book_site_visit` and `transfer_to_human` and allows "Let me check / One second / Let me note that down" | none (v2.1 only) | Yes | Compatible with 008's wording; if 008's `not_confirmed` path means the booking may fail, the line must stay a pause and never a confirmation. It already says so. |
| Site-visit line ("…call book_site_visit as soon as they give one…After booking, confirm the day and time in one sentence") | `:125` | No (shared) | Mentions the confirmation 008's failure path must not contradict. |
| Sample "Caller: Saturday at eleven works for me." answered "I've put you down for Saturday at eleven in the morning." (v2) / "You're down for Saturday, eleven in the morning." (v2.1, shortened in r3) | `:151-152` | Both variants | States a done booking; fine after a result, wrong if the result was a failure. 008's call; there are two lines to edit now, one per variant. |
| `date.today()` in the prompt's [CURRENT DATE] | `:62` | No | The UTC issue from 008's spec stays open. |

`test_prompt.py` is not edited by 018, so 008's one edit there (`test_p08`) cannot conflict. 019: no shared code (Change 0); the only meeting point is the one-line `tts_model` variable (Change 2).

## Data touched

| What | Read or write | By whom | Notes |
| --- | --- | --- | --- |
| `projects.config -> 'pricing'`, `'unit_types'` (both entries), `'overview'`, `'amenities'` | **Write**: add a `spoken` string each | 🧑 **founder's SQL**, outside this PR, run before the exit test | Reviewed and tested by you on a copy. Not drafted, run or touched by an agent. |
| `projects.config -> 'competitors'` | **Write**: removed | 🧑 founder's SQL | Same. |
| `projects.config` (all of it) | Read by the app per call (cached) | the app | Unchanged. The app reads `project_name`, `developer`, `location.city`, `location.sector` for key terms. |
| Redis `convo:config` (hash, no TTL) | **Read** once per call by the app; **written only by you** with `redis-cli` | 🧑 founder | Fields in Change 0. Cleared with `DEL`. New key; nothing else reads it. |
| Redis `session:call:<call_sid>` | Read only in the exit test | 🧑 founder | Same fields as 014. |
| Container log (`docker logs nxlyr_agent`) | New INFO lines: `convo config:`, `stt endpoint:`, `stt check:` | the app | Sanitised as in Change 5; no key, URL or transcript. |
| `tenants`, migrations | None | | Never `SELECT *` on `tenants`. |

## Acceptance tests (automated)

Main checkout's interpreter, no network, no OpenAI call. All existing modules keep passing unchanged: `agent.test_prompt` (the whole v2 suite, because the defaults are v2), `agent.test_startup_timing` (two patch lines), `agent.test_kb_loader`, `agent.test_turn_release`, `agent.test_ws_auth`, `agent.test_demo_guard`, `agent.test_log_hygiene`. At `e3dca41`, 32 pass in the first two.

`agent/test_prompt_v21.py`:

- **N00 (v2 untouched):** `build_system_prompt()` with the default arguments equals the stored golden string byte for byte, both disclosure modes; `BANNED_OPENERS` still equals the v2 tuple; `build_initial_messages()` defaults are v2.
- **N01:** v21 has the blocks `[CORE RULES]`, `[REAL ESTATE PACK]`, `[HOW THE CALL GOES]`, `[COMPANY]` in that order, once each, before `[CURRENT DATE]`.
- **N02:** the banned phrases (v21 tuple) appear nowhere in the v21 prompt outside the ban line, nor in greetings or the closing phrase, except "Right, so" as the connective; `BANNED_OPENERS_V21` equals the tuple in Change 1.
- **N03 (samples):** nine `You:` lines; none has a digit, "Rs", a banned phrase, a bracket, "send", "WhatsApp", "shortly" or "soon"; **the first sentence of every `You:` line is eight words or fewer** (r3); at most 4 end in `?`; "Hi Aarya." is answered by a line starting "Hi" that contains neither "Aarya" nor "Next Layer"; the "Hello?" answer is "Yes, I can hear you."; at most one sample starts with "So" and at most one with "Okay so"; the lead-in line is present once.
- **N04:** the rules exist, each once: first-sentence rule; connectives with "one reply out of three"; pre-tool line naming `book_site_visit` and `transfer_to_human`; "um" and "uh" only inside a prohibition; one-question rule; link-to-needs rule; correction rule; unclear-audio rule; the amounts rule with "below half the lowest price or above double the highest" and "Just to check"; the `spoken` rule.
- **N05:** "Did you mean" is not in the v21 prompt as something to say; "Never ask whether they meant it" is present; `{project_name}` appears in the near-miss rule.
- **N06 (greetings):** the COMPANY block contains the three separate cases (greeting at the start answered "Hi, yes, I'm here.", mid-call check answered "Yes." or "Yes, I can hear you.", who/which company/why said once); the old "Never greet or introduce yourself again" sentence is absent in v21; the greeting still appears exactly once in `build_initial_messages` (P13-equivalent for v21).
- **N07 (carried over):** every line marked "same" in the table is present verbatim in v21 (disclosure sentence, `end_call` rule, `transfer_to_human` rule, no-name rule, no-promise rule, closing phrase, payment-plan sentence).
- **N08 (size):** empty-KB v21 prompt at most **8,664** characters; the test prints the actual size.
- **N09 (greeting words):** `build_greeting` output is unchanged for `tags=False` in all existing cases; with `tags=True`, stripping tags and collapsing spaces equals the plain text (both disclosure modes, with and without a project name); tags never appear in `build_initial_messages` output; no unresolved `{…}` in either variant.

`agent/test_convo_config.py`:

- **C01:** no hash, `None`, or `{}`: every default (`v2`, `off`, `off`, `global`, `off`), `overrides=none`.
- **C02:** each valid value is applied; case and surrounding spaces are tolerated; the `overrides=` list names exactly the fields set.
- **C03:** table-driven invalid values (`v3`, `V2.1`, `yes`, `EU-west`, empty, a 500-character string) fall back to the default with one WARNING naming the field and not repeating the long value; the call is not broken.
- **C04:** an unknown field (`stt_keyterm`) logs one WARNING and changes nothing.
- **C05:** `read_convo_config` with `REDIS_URL` unset, a client that raises, and a client whose `hgetall` sleeps 5 s each return the defaults in under 1 s, log a WARNING with the exception class only, and close the client.
- **C06:** `log_line` matches `^convo config: conn=(?:[0-9a-f]{6}|-) prompt_version=\S+ stt_keyterms=\S+ stt_numerals=\S+ stt_region=\S+ greeting_tags=\S+ read_ms=\d+ overrides=\S+$` and contains no `REDIS_URL` or key value set in the test environment.
- **C07:** `tags_allowed("eleven_v4_turbo")` is true; `"eleven_flash_v2_5"`, `"eleven_turbo_v2"`, `None` and `""` are false.

`agent/test_stt_keyterms.py`:

- **K01-K03:** `build_keyterms` with the real-shape KB returns `Meridian Heights`, `Aetheria Realty Group`, `Gurugram`, `Sector 79B` and the six fixed terms with no landmark, no duplicates, all non-empty `str`, none containing `:`; non-string or missing values are skipped; an empty KB gives the six fixed terms; a KB with 500 long values gives at most 40 terms and 400 estimated tokens.
- **K04:** with all three switches off, the settings and constructor arguments built for `SttCheckingDeepgramService` equal today's field for field (`keyterm` and `numerals` not given, no `base_url`).
- **K05:** with keyterms and numerals on, `_build_connect_kwargs()` has `keyterm` as a list, `numerals == "true"`, `language == "en-IN"`, `model == "nova-3"`, and `encode_query` of it gives repeated `keyterm` pairs. No network. (UNVERIFIED whether the method needs `sample_rate` set first; the builder sets it on the stub.)
- **K06 (EU):** with `base_url="api.eu.deepgram.com"` the client environment's `production` is `wss://api.eu.deepgram.com`; with the environment constructor patched to raise, the service logs the WARNING and the `stt endpoint:` line says `host=` the default host and logs the mismatch WARNING when `region=eu`; with the attribute path unreadable the line says `host=unknown` and nothing raises.
- **K07-K09 (sanitiser):** table-driven: "tell me about Eridian Heights" gives `project=near:"Eridian Heights"`; "Meridian Heights" gives `exact`; "my number is 98765 43210" gives `amount=none` and no digit run of five or more in the output; "my name is Rahul Verma and I live at 12 MG Road" gives `project=none amount=none` and the output contains neither name nor street; "1.2 crore" gives `amount="1.2 crore"`; "about two" gives `none`; "2" gives `"2 [no unit]"`; "forty lakhs" gives `amount="forty lakhs"`. The check line passes the frame on unchanged, logs one line per final frame and none per interim frame. Through the real `log_scrub` sink, a final transcript with a 10-digit mobile number, a name and a street yields a line containing none of the three.
- **K10:** `conn=-` when `conn_id` is `None`.

Greeting and `bot.py` wiring (in `test_convo_config.py`, driving `run_bot` the way `test_startup_timing` does, with services patched):

- **G01:** `greeting_tags` off: the `TTSSpeakFrame` text equals the plain greeting.
- **G02:** `greeting_tags` on with `tts_model = "eleven_flash_v2_5"`: the frame text is the plain greeting, one WARNING, `greeting_tags=blocked` in the log line.
- **G03:** `greeting_tags` on with `tts_model` patched to `"eleven_v4_turbo"`: the frame text is the tagged greeting; the context's `messages[-1]` is still plain.
- **G04:** default config: `build_initial_messages` is called with `version="v2"`; with `prompt_version=v21` it is called with `version="v21"`; the `prompt v2:` line ends with `version=v2` or `version=v21` and keeps its existing prefix `prompt v2: chars=… lead_source=… disclosure_mode=… company=…`.
- **G05:** exactly one `convo config:` line per call.

`agent/test_prompt_harness.py` (fake OpenAI client, no key):

- **H01-H02:** `--script` splits on `---`, ignores `#`, feeds lines in order from the seeded greeting; `--runs 3` runs three passes; `--prompt-version` selects the variant.
- **H03 (flags):** "my name is Aarya" after the first reply is `reintro`, but not when the caller line asked "who is this?"; "Hi, yes, I'm here." is not `reintro`; "Great, …" and a bare "Right." are `banned`, "Right, so it starts at…" is not; "Did you mean …?" is `didyoumean`; "Rs 12 thousand" is `digits`; "[warm] Hi" is `tag_in_reply`; two question marks is `two_questions`; 46 words is `over45`; none flagged for "So, it starts at two point two crore. That is for the three bedroom."
- **H04:** a fake message with both `content` and `tool_calls` prints a `Bot (before tool):` line.
- **H05:** the summary counts repeated sentences, connectives and process phrases correctly on a fixed fake transcript.
- **H06:** the default KB is `prompt_scripts/kb_meridian_heights.json` and `load_kb` (Supabase) is never called; `--kb live` calls it; the file parses, has `spoken` on `pricing`, both `unit_types`, `overview`, `amenities` and `payment_plan`, has no `competitors`, and has the same top-level keys and the same values as the JSON block in this spec (the reviewer also diffs the file against that block; no test reads `docs/`).
- **H07:** neither stdout nor `--out` contains the `OPENAI_API_KEY` value set in the test environment.
- **H08:** `--partial-greeting` seeds the first six words only.

Import smoke from `agent/`: `import server, week2_latency_observer`. `bot.py` diff review: only the three hunks listed (the reviewer checks the diff touches no line outside 79 / 104-111, 443-455 plus the insert before 446, 490-498).

Not automatable, so not claimed: that Deepgram accepts the parameters on a real streaming connection (global or EU), that key terms improve recognition, that the EU endpoint is faster for transcripts, that the tagged greeting sounds right, and that any of it sounds natural.

## Exit test (what the founder does by hand)

Tags: 🧑 YOU, 👀 VERIFY. Paths use full quotes. The design isolates each piece with switches, so a difference between two neighbouring blocks has one cause. The blocks run **back to back**, one snapshot after each (your answer 2 to r2: no interleaving, no new tool option).

### Before the merge

1. **The knowledge base: DONE (founder).** The config you pasted is the live one: you ran your SQL at about 18:20 (founder-reported; it returned 1 row and statement 4 was clean). The five `spoken` lines are in and `competitors` is gone. Nothing to run.
2. 🧑 **Harness, with your own key; report the first-sentence figure before any call.** In the shell where you run it:

```bash
export OPENAI_API_KEY=...        # you type it; do not paste it anywhere
cd "/Users/vansh/Desktop/SALES AGENT/nxlyr-worktrees/018-conversation-v21/agent"
"/Users/vansh/Desktop/SALES AGENT/nxlyr/agent/venv/bin/python" prompt_harness.py --prompt-version v2  --script prompt_scripts/conversation_v21.txt --runs 3 --out ~/Desktop/harness-018-v2.txt
"/Users/vansh/Desktop/SALES AGENT/nxlyr/agent/venv/bin/python" prompt_harness.py --prompt-version v21 --script prompt_scripts/conversation_v21.txt --runs 3 --out ~/Desktop/harness-018-v21.txt
"/Users/vansh/Desktop/SALES AGENT/nxlyr/agent/venv/bin/python" prompt_harness.py --prompt-version v21 --script prompt_scripts/conversation_v21.txt --runs 3 --partial-greeting --out ~/Desktop/harness-018-v21-partial.txt
```

   Leave `REDIS_URL` unset. 👀 Read the two files side by side. Check: more human; no banned opener, no "did you mean", no repeated name, company or reason, no digit; S4 answers use "Meridian Heights"; S5 gives the expected answers (1.2 crore taken as heard with where prices start, "about two" asks the unit, 40 lakhs and 12 crore confirmed once, 2.5 crore taken as heard); S7 asks to repeat and then simplifies; S8 takes the correction; S9 links to the parents and the "just looking"; **S10: does she say "December 2029" and "twenty-five minutes" as words** (the KB still holds those as digits, finding F-g). **Report to me** the summary lines for v2 and v21: p50 first-sentence words and ms, connective and process-phrase counts, replies with two questions, repeated sentences, replies over 45 words. **Decision point:** if the v21 p50 first sentence is well above 100 ms or the replies read curt, edit the prompt (the samples first) before any call is made.

### Calls

3. 🧑 After the merge deploys, check it twice:

```bash
gh run list --workflow=deploy.yml --limit 1
ssh nxlyr-vps "docker ps --format '{{.Names}} {{.Status}}'"
```

   Repeat the `docker ps` line after 10 s. 👀 Green for the merge commit; healthy both times.
4. 🧑 Setup (the 014 limits), a clean switch state, T0, and the snapshot helper:

```bash
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET demo:config phone_limit 100 ip_limit 100 phone_cooldown_seconds 5 ip_cooldown_seconds 5"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL convo:config"
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$T0"
snap() { ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/" && scp nxlyr-vps:/tmp/section6_real_call_events.log "./events-$1.log" && ssh nxlyr-vps "rm -f /tmp/section6_real_call_events.log"; }
```

   (`snap` copies the cumulative events log to a named file; run everything in the same terminal tab so `T0` and `snap` survive.)
5. 🧑 **Smoke call, first, with everything on.** Set and place one call; say "Hi Aarya" and, in a sentence, "my budget is around one point two crore":

```bash
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config prompt_version v21 stt_keyterms on stt_numerals on stt_region eu greeting_tags off"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL convo:config"
ssh nxlyr-vps "docker logs nxlyr_agent -t --since $T0 2>&1 | grep -E 'convo config|stt endpoint|stt check|prompt v2:|Connection lost|connection error|Custom base_url' | tail -30"
```

   👀 The bot answers (speech recognition connected on EU with key terms and numerals). `convo config:` shows `prompt_version=v21 stt_keyterms=on stt_numerals=on stt_region=eu overrides=…`; `stt endpoint:` shows `region=eu host=api.eu.deepgram.com`; `prompt v2:` ends `version=v21` and `chars=` is the new size; `read_ms` is a few milliseconds; no "Connection lost", "connection error" or "Custom base_url" line. **If the call had no speech recognition: `HSET convo:config stt_region global`, call again. If it still fails, `HSET … stt_keyterms off stt_numerals off`, call again; the combination that fails is your answer to the `en-IN` and EU questions. Stop and tell me before continuing.** This is the first call after the deploy, so it is cold and its instance number is **S** (read it from the `latency_report.py` header: `python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-smoke.log --md` after `snap smoke`).
6. 🧑 **Call G, greeting tags on a Flash voice (the guard).** `HSET convo:config greeting_tags on`, place a call, stay silent 20 s. 👀 You hear the **plain** greeting (no tag words, no odd sounds); the log has one WARNING `greeting_tags is on but the voice model is not v4` and `convo config:` shows `greeting_tags=blocked`. Then `HSET convo:config greeting_tags off`. This is instance **S+1**. (The positive case waits for 019 and v4; see the optional step at the end.)
7. 🧑 **Warm-up call, uncounted** (your answer 2). Set block 1's configuration (below), place one call, say "Hi Aarya" and two or three more lines, hang up. It is instance **S+2**. It is not scored and not in any report, because every report below starts at the first instance of a block with `--from-call`. Its purpose is to leave the voice and the model warm and the path on block 1's configuration before any counted call.

**Part A: 13 script calls in four blocks**, one call at a time, 10 s apart, same phone and room. The 014 script (steps 1-11, with 7a) with the three new steps inside existing turns: **step 1 "Hi Aarya"** instead of "hello" (the first call of each block over the greeting, the rest after it; keep the variant balanced as in 014: calls 1-5 over, 6-10 after, counting through Part A); **step 4** "my budget is around one point two crore" in a sentence; **step 5** "tell me about Meridian Heights" in a sentence. Before each block set its configuration and read it back; after the block run `snap`. S is the smoke call's instance.

| Block | Calls (instances) | `prompt_version` | `stt_keyterms` / `stt_numerals` | `stt_region` | Compare with | What the difference shows |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 3 (S+3 to S+5) | v2 | off / off | global | (control = today) | the baseline for today, same day, phone, room |
| 2 | 3 (S+6 to S+8) | v21 | off / off | global | block 1 | **speaking style**: v2 against v2.1, hearing and region held |
| 3 | 3 (S+9 to S+11) | v21 | on / on | global | block 2 | **hearing**: key terms and numerals, style and region held |
| 4 | 4 (S+12 to S+15) | v21 | on / on | eu | block 3 | **speech-recognition latency**: EU against global, everything else held |

```bash
# before block 1 (also the warm-up call, step 7)
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config prompt_version v2 stt_keyterms off stt_numerals off stt_region global greeting_tags off"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL convo:config"
# before block 2
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config prompt_version v21 stt_keyterms off stt_numerals off stt_region global"
# before block 3
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config stt_keyterms on stt_numerals on"
# before block 4
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET convo:config stt_region eu"
```

After each block run `snap b1`, `snap b2`, `snap b3`, `snap b4`. 👀 After every set, the **next** call's `convo config:` line must show the block's values; if it does not, redo that call. Take a stopwatch from pickup to the first word on the first call of each block (data).

   **Which figure shows what, with `latency_report.py`.** Each snapshot ends where its block ends, so `--from-call` with the block's first instance isolates that block (the tool has no upper bound, so the snapshot is the upper bound):

```bash
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-b1.log --from-call $((S+3)) --md
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-b2.log --from-call $((S+6)) --md
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-b3.log --from-call $((S+9)) --md
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-b4.log --from-call $((S+12)) --md
# all ten v2.1 calls together (the gates)
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events-b4.log --from-call $((S+6)) --md
```

   - **Speech-recognition latency (block 4 against block 3): the "STT first result" row, p50 and p90.** The expected effect is roughly one round trip, about 120 ms, from your TCP measurement (UNVERIFIED as a transcript effect). Because the turn strategies wait for the transcript (`bot.py:244-251`), a real STT gain should also show in "user turn release" and in "sum of stages, no tool"; if "STT first result" moves and neither of those does, the saving is hidden behind the turn analyzer. With 3 and 4 calls (about 30 to 45 turns each), compare p50 and p90 and treat differences under ~30 ms as noise. Blocks run back to back, so the network can differ by time of day between block 3 and block 4; note the clock time of each block.
   - **Speaking style (block 2 against block 1): the "first-sentence wait" and "LLM first token (first call)" rows**, plus your ear. This is also where the larger prompt shows up (F-f).
   - **Hearing (block 3 against block 2, and blocks 1-2 against 3-4):** not the latency report; the `stt check` lines below.
   - **Gates:** "first-sentence wait" p50 on the all-v2.1 report (instances S+6 to S+15, ten calls).
   - **Pre-agreed cut rule (your answer 3 to r2).** Compare the "LLM first token (first call)" **p50 of block 2 with block 1**. If block 2 is **more than 50 ms higher**, cut the **correction rule** first (rule 10, "If the caller corrects you…"); if the p50 gap is still over 50 ms after that cut, cut the **[HOW THE CALL GOES]** section. **Keep the unclear-audio rule** (rule 11): it is the candidate fix for the call-3 re-introduction. Cutting nothing otherwise. Mechanically a cut is a prompt edit by me and a redeploy; because the gates are about the final text, **my recommendation is to rerun blocks 2 to 4 (ten calls) on the cut text** before judging the gates. Nothing is cut before the numbers say so.

   **What Deepgram heard, grouped by config, without transcripts:**

```bash
ssh nxlyr-vps "docker logs nxlyr_agent -t --since $T0 2>&1 | grep -E 'convo config|stt endpoint|stt check' | grep -E 'convo config|stt endpoint|project=(near|exact)|amount=\"'"
```

   👀 Each call starts with its `convo config:` line; the `stt check:` lines after it (same `conn=`) are that call. For steps 4 and 5 record: project heard exact / near / none; amount heard right / wrong unit / no unit; and whether numerals made `1.2 crore` or left words. Compare the **off** group (blocks 1 and 2: six calls) with the **on** group (blocks 3 and 4: seven calls). Reported as data (your answer 8), no gate.

After block 4, before Part B, the checks from 014:

```bash
grep -cE '[0-9]{10}' ./events-b4.log
ssh nxlyr-vps 'for k in $(docker exec nxlyr_redis redis-cli --scan --pattern "session:call:*"); do echo "$k"; docker exec nxlyr_redis redis-cli HMGET "$k" site_visit_booked end_call_tool_invoked transfer_requested call_outcome; done'
ssh nxlyr-vps "docker logs nxlyr_agent 2>&1 | grep -c 'TOOL end_call'"
```

   The `grep -c` prints 0; `TOOL end_call` prints 0 for everything so far (the smoke, G and warm-up calls say no goodbye); every Part A key shows `end_call_tool_invoked=false`. The `TOOL …` and `prompt v2:` lines are in the container log, not `events.log`.

**Part B: 5 more calls** (all five kept, your answer 1), on the config you would choose as the new default after reading Part A: set it now and write it down. If blocks 3 and 4 were fine that is `v21 / on / on / eu`; if EU was worse or failed, `global`. Calls 11-12 silent for 30 s; call 13 "hello" then "are you a bot?"; call 14 the normal conversation to step 5, then "are you a bot?"; call 15 steps 2-9 to the Saturday 11 am booking, then "okay, thanks, bye". `TOOL end_call` over the whole log since T0 must print exactly **1**. On one call ask "which company is this?". Each call's `convo config:` line shows the config used.

Then restore the limits and the switches, and run the leak regression:

```bash
"/Users/vansh/Desktop/SALES AGENT/tools/leak_counts.sh" "$T0"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL demo:config"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL demo:config"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli GET demo:kill"
```

   Leave `convo:config` set only if you intend production to run it; otherwise `DEL convo:config` (everyone, including prospects, gets the switches while it is set). Total: 1 smoke + 1 G + 1 warm-up (uncounted) + 13 Part A + 5 Part B = 21 calls placed, **20 counted**.

**Optional, after 019 is merged and the voice is v4:** set `greeting_tags on`; the `voice config:` line shows the v4 model; call once. 👀 The greeting is the tagged version spoken with no tag read aloud; `convo config:` shows `greeting_tags=on`; greeting TTS first audio is not worse. Not part of this task's pass bar.

**Scoring sheet** (🧑 one row per counted call, with the config in force): the 014 columns (natural Y/N, filler opener, echo, lists/question every line, full project name repeated, digits or "Rs" spoken, price objection handled, payment plan as a sentence, name or "sir" or "ma'am" used, AI denied or dodged, ended after booking, second greeting) plus: "Hi Aarya" answered with a natural "Hi" back (Y/N), a repeated name, company or reason (Y/N: this and only this is a second greeting), mid-call "are you there" handled with "Yes" (Y/N, if it came up), connectives used (count; too many?), closing question about a third of the time (Y/N), more than one question in a reply (count), project heard exact/near/none, reply used the right name, "did you mean" asked (must be N), amount heard right, unit question only when needed, below-range amount answered with where prices start (step 4), garbled or cut-off audio handled by asking to repeat (if it came up).

**Pass bar (the brief's gates, nothing added):**

1. **First-sentence wait p50 under 100 ms** on the ten v2.1 calls (blocks 2 to 4, the last report above). If it misses, one rerun of those ten calls decides, as in 014.
2. **At least 7 of those 10 v2.1 calls natural by ear.** (Block 1's three v2 calls are scored too, as data.)
3. The 014 zero-tolerance items, **unchanged, one occurrence fails, on every counted call including the silent ones and Part B**: an invented name, "sir" or "ma'am"; an AI denial or dodge; ending the call after a booking without the caller saying goodbye; a second greeting or re-introduction (a repeated name, company or reason; a "Hi" back is not one).
4. Leak gates all 0 and no ten-digit number in the events log.

Reported as data, not gates: STT first result p50 and p90 per block (the region effect), project and amount heard per group (your answer 8), LLM first-token p50 per block (014 gate 716 ms, missed at 726 ms; the cut rule above), the `read_ms` of the config read, the 015 start-up figures (`call timing:` lines: `ws_connected` to `first_bot_audio_sent` against the 015 gate of 1,500 ms, to see that the extra Redis read and the larger prompt did not cost start-up), the per-call stopwatch, and the harness first-sentence figures from step 2. Paste the scoring sheet, Redis output, the five reports, the `stt check` extract and the leak counts into the PR's Evidence section.

**After the pass: defaults flip in a small follow-up PR** (code defaults become `v21`, key terms on, numerals on, and `eu` only if its block was better; `v2` stays selectable). Until then, with no `convo:config` set, production behaves as today.

## Sources

Public sources behind the changes. No research files were added to the repo. "Fetched" means I read the page text this session; "search only" means I saw a search-result summary and did not read the page.

- **OpenAI, Realtime prompting guide** (fetched): <https://developers.openai.com/api/docs/guides/realtime-models-prompting>. The model "closely follows sample phrases"; the sample-phrases instruction "DO NOT ALWAYS USE THESE EXAMPLES, VARY YOUR RESPONSES"; the Variety rule "Do not repeat the same sentence twice"; unclear audio: "Only respond to clear audio or text", do not guess, "Don't repeat the same unclear-audio clarification twice"; preambles: "Use one short sentence", for example "I'll check that order now." Behind the samples change, the variety line, rule 11 and rule 5. **Caveat:** the guide is for speech-to-speech realtime models; our pipeline is speech-to-text, GPT-4o text, then TTS, so the guidance is applied by analogy.
- **Softcery, "Voice agent prompt engineering"** (fetched; Nazar Bidenko and Mariana Kostiuk, published 22 May 2026): <https://softcery.com/lab/voice-agent-prompt-engineering>. Filler: the article says filler "makes a professional service agent sound unsure," and presents no filler as a persona decision for a business agent, not a universal rule. This is in tension with the connectives you chose to allow; the rate limits (one reply in three, never twice in a row) are the compromise, and block 1 against block 2 is the test of it. Corrections: one short acknowledgement, then continue, and a repeated "I apologise for the confusion" destroys trust; behind rule 10. One question at a time: behind rule 6. It also advises putting examples at the end of the prompt (ours are last) and starting with a minimal prompt, adding rules only for behaviours that fail in testing, which supports the pre-agreed cut order after block 2. It does not address whether sample phrases are copied; that point rests on OpenAI's guide.
- **Vapi, Voice AI Prompting Guide** (search only; also quoted in Softcery's article for "roughly two sentences and one question at a time"): <https://docs.vapi.ai/prompting_guide>. "One question at a time": asking several questions in one turn confuses callers. Behind rule 6.
- **Gong Labs, "Nailing your sales discovery calls"** (fetched): <https://www.gong.io/resources/labs/nailing-your-sales-discovery-calls/>. 519,000+ B2B call recordings; success peaked at about 11 to 14 questions; top performers spread their questions across the call while average ones front-load them like a checklist; the article cautions correlation is not causation. **B2B data, so the direction only:** behind [HOW THE CALL GOES].
- **Jefferson (1983),** "On exposed and embedded correction in conversation," *Studium Linguistik* 14: 58-68 (listed on the EMCA wiki, <https://emcawiki.net/Jefferson1983>): the source of the term **embedded correction**, which the near-miss rule applies: the correct name is simply used in passing, with no stop to dispute the error. Background on repair and the preference for self-correction: **Schegloff, Jefferson and Sacks (1977),** *Language* 53(2): 361-382, doi:10.2307/413107. I confirmed both citations' details by search and did not read either text.

## Risks and rollback

- **A switch combination that Deepgram rejects (biggest risk, UNVERIFIED).** Effect: a call with no speech recognition. Caught by the smoke call; every piece has its own switch (`stt_region`, `stt_keyterms`, `stt_numerals`), which you turn off with one `redis-cli` command and no deploy. With no `convo:config`, nothing in this task changes Deepgram's behaviour.
- **EU endpoint down or slower.** It fails closed (no fallback region, per Deepgram). `HSET convo:config stt_region global`. The constructor's silent fallback to the US host is detected by the `stt endpoint:` line (Change 3).
- **A bad value in Redis.** Falls back to the default with a WARNING; a typo in a field name warns; a down Redis costs at most about 0.5 s at pickup and then runs defaults.
- **Pickup latency.** One extra Redis read per call (about 2 ms measured by 015 for the connection, plus one round trip). `read_ms` is logged; the exit test compares the 015 start-up figures.
- **The v2.1 prompt is larger** (F-f: 8,364 characters empty-KB against 4,771; 11,547 with the real KB against 7,948 for v2) and may raise LLM first-token time. Block 1 against block 2 shows it, and the cut rule is pre-agreed. v2 is one command away.
- **The 100 ms gate may still miss.** The three long samples are now eight-word versions (F-b), but "finish each thought" still pulls first sentences long. The harness reports it before any call.
- **Over-use of connectives and "Let me check"** (a new tic, and in tension with Softcery's "no filler for a professional agent"). "One in three, never twice in a row" are hints to a model that does not count; the harness summary prints the real rate and the scoring sheet has a column. The pre-tool line sits before real pauses (rule 5).
- **A pre-tool line that confirms.** The text is spoken before the function runs (Library claims). The rule forbids saying it is done; the harness shows the text beside the call, and 008's truthful-result work depends on this staying a pause.
- **Near-miss rule swallows a genuinely different project name.** Mitigated by the "clearly a different project" sentence; S4 shows it.
- **Digits left in the KB** (F-g): `objections.possession_timeline` ("December 2029 (3 years)"), `objections.location` ("25 minutes") and `overview.usps` ("3-side", "80%") have no `spoken` version. The write-for-the-ear rule is the only guard. S10 tests it before any call.
- **Re-introduction may not be fixed** (cause unknown); the changes are aimed at the plausible causes and checked over repeated harness runs and 20 counted calls.
- **The tagged greeting on a non-v4 voice** would read tags as words or make odd sounds. Off by default; the guard needs `tts_model` to start with `eleven_v4`; test G02 and the exit-test call G cover it.
- **`stt check` logs a near-miss fragment** (accepted, your answer 5): bounded, sanitised, scrubbed.
- **Blocks back to back** can differ by time of day (most likely to blur block 3 against block 4); the clock time of each block is noted. This was your choice (answer 2).
- **Merge overlap with 019 and 020 in `bot.py`:** my hunks are the imports, the insert before 446 plus 443-455, and 490-498. No line of the TTS block (466-482), `on_client_connected`, turn strategies or serializer changes. The one-line `tts_model` variable is the only place 018 and 019 meet.
- **Rollback.** Before the defaults flip: `DEL convo:config` returns the whole behaviour to today's, with no deploy. Revert the PR for a code-level rollback (merge = deploy). The KB `spoken` fields are additive and harmless to v2. Hard rules respected: no SQL executed or drafted by an agent, no key read, no VPS access, no `.env*` read.

## Open questions for me (the founder)

**All answered by the founder's approval of r3.** He accepted the seven recommendations below as written and gave the fact for item 1. Nothing is open.

1. **Live config or tested copy?** **Live.** The SQL ran at about 18:20 (founder-reported); exit-test step 1 is marked done.
2. **Digits still in the KB outside the five spoken lines** (F-g). **Decision: leave the possession and distance digits alone in this PR; harness scenario S10 decides.** If S10 shows a problem, adding `spoken` lines for `objections.possession_timeline` and `objections.location` is your SQL, outside this PR.
3. **The `tts_model` meeting point with 019.** Accepted: the single variable that the later-merging task sets (Change 2).
4. **Tags tied to the prompt version?** Accepted: no; `greeting_tags` works with either `prompt_version`.
5. **Key terms and numerals measured together.** Accepted: together in blocks 3 and 4; the switches stay separate.
6. **Greeting words.** Accepted as written; the founder bracket in Change 2 stays for you to delete or replace.
7. **Warm-up call content.** Accepted: block 1's configuration, "Hi Aarya" and two or three lines, then hang up (step 7).

### Resolved from r2 (your answers, applied)

| r2 question | Your answer | Where applied |
| --- | --- | --- |
| 1 Long samples | Use the eight-word versions, show them in the spec | Change 1 (table "Samples, r2 against r3"), F-b, test N03 |
| 2 Interleaving | No interleaving, no new tool option; blocks back to back with a snapshot after each; add one uncounted warm-up call before block 1 | Exit test (steps 4 and 7, block table, risks) |
| 3 Prompt size | Cut nothing yet. If block 2's LLM first-token p50 is more than 50 ms above block 1's, cut the correction rule first, then [HOW THE CALL GOES]; keep the unclear-audio rule | Exit test (cut rule), Risks |
| Sources | Softcery URL given; Jefferson 1983 is correct for "embedded correction" | Sources |
| Stand-in KB | Do not reconstruct anything; the full real config was pasted | Change 6 (the file is the pasted config, verbatim), UNVERIFIED list |
| Others | Answer with my recommendation | This list; all seven accepted on approval, plus: config is live, digits left alone, S10 decides |

### Resolved from r1 (your answers, applied)

| r1 question | Your answer | Where applied |
| --- | --- | --- |
| 1 Part B | Keep all five calls | Exit test, Part B |
| 2 "Hi Aarya" | "Hi, yes, I'm here."; mid-call checks get "Yes."; a "Hi" back is not a second greeting; "sir", "ma'am", names wait for 012 | Change 1 (COMPANY, samples), Change 6 flags, Non-goals |
| 3 three new steps | Inside existing turns | Fixed caller lines, Exit test |
| 4 100 ms gate | Accept rule 2, keep the gate, report the harness figure first | Change 1 rule 2, Exit test step 2 |
| 5 near-miss fragment | Fine | Change 5 |
| 6 prompt size | Cap = size + 300, report the size | Change 1, test N08 |
| 7 real KB | Values given; key terms project, developer, city, sector; no UPDATE drafts | Changes 3, 4, 6 |
| 8 STT bar | Data, no gate | Exit test |
| 9 kill switch | Yes, in Redis | Change 0 |
| 10 ban list | OK; a bare "Right." must be caught | Change 1, Change 6 `banned` |
| 11 `prompt v2:` label | Keep, append `version=` | Change 0, test G04 |
