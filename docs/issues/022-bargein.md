# 022: Barge-in that tells a real interruption from a cough or a "haan"

Status: APPROVED by the founder on 2 Nov (answers to the five questions folded in below). Builder: Codex. Reviewer: Claude (must differ from the builder).
Worktree: `../nxlyr-worktrees/022-bargein`, branch `task/022-bargein`, from `origin/main` 3b545d7.
Note: 018's "Out of scope" calls this task "020-bargein"; the number is now 022.

## Goal

A cough, fan noise or an agreeing "haan" no longer stops Aarya mid-sentence, and a real interruption ("wait", a question) stops her faster.

Covers founder priority 2 (30 Oct). Founder's measurements, 25 Oct: at the ear, a cough did not stop her but any spoken word did, including "haan"; on speakerphone, any loud noise stopped her (a fan stopped her on call 12 of 24 Oct); after a real interruption she kept talking for about 0.5 s (stopwatch, plus or minus 0.3 s). Inbox note `2026-10-24-backchannel-vs-barge-in-interrupts-on-any-vad.md`: she interrupts on any VAD trigger.

Everything new sits behind `convo:config` field `bargein_mode`: `legacy` (default, today's behaviour) or `smart`. A call without the field behaves as it does today.

## Non-goals

- Anything while the bot is **listening**. Turn start, turn end and first-sentence latency do not move (see the VAD risk below).
- The prompt, the TTS block, the STT block and language settings (019, 021).
- Changing what happens to a user turn that is already running, or the 0.8 s turn-release backstop (011).
- Fixing audio chunk sizes or send-ahead pacing toward Exotel (noted under Risks, not changed here).
- RNNoise or any other noise filter, and any new dependency (founder, 2 Nov: its own task later, only if speakerphone noise still gets through).
- Changing the word lists for any language other than English, Hindi (Latin script) and Hindi (Devanagari).
- Any schema, SQL or dashboard change.

## What I checked

Pipecat 1.5.0 is the version in the main checkout's venv (`agent/venv/lib/python3.12/site-packages/pipecat`, `pip list`). Line numbers are from that install and from this worktree.

| Where | Lines | What I found |
| --- | --- | --- |
| `agent/bot.py` `build_user_turn_strategies` | 195-259 | `start = [VADUserTurnStartStrategy(enable_interruptions=True), TranscriptionUserTurnStartStrategy(enable_interruptions=True)]` (221-224). Stop strategies 226-259 (011). This is why every VAD start interrupts. The comment at 202-217 is already correct about interrupted text (see "Settled" below). |
| `agent/bot.py` `_build_user_aggregator_params` | 262-269 | `SileroVADAnalyzer()` with default params. Called inside `asyncio.to_thread` at 566, after `convo_cfg` is read at 472. |
| `agent/bot.py` serializer, transport, pair, observers | 442-451, 453-467, 574-577, 594-606 | `ExotelFrameSerializer(stream_sid=..., call_sid=..., params=...)`; `CallTimingObserver` (324-359) is the existing observer pattern. |
| `agent/convo_config.py` | 17-30, 33-42, 51-94, 134-156 | `_ALLOWED`, `_DEFAULT_RAW`, `ConvoConfig`, `parse()` and `log_line()`. Invalid value logs a warning and keeps the default. |
| Pipecat `serializers/exotel.py` `serialize` | 98-100, 114-118 | Clear is `{"event":"clear","streamSid":...}` and media is `{"event":"media","streamSid":...,"media":{...}}`. Camel case. Confirmed. Constructor 52-77. |
| Exotel docs (the article named at `exotel.py:37`) | n/a | A WebFetch summary of the article says every example uses `stream_sid` (clear and outbound media) and that clear drops audio "sent before but not yet played". **UNVERIFIED**: I did not read the raw article and no real clear has been observed. `agent/mock_exotel_client.py:28-52` already records the same doubt from the same docs. Outbound media with `streamSid` plays today, so Exotel tolerates that key on media; whether it honours it on clear is the open question. |
| Pipecat `transports/websocket/fastapi.py` | 463, 492-507, 519-556, 588-597 | `InterruptionFrame` goes to `serializer.serialize()` (501-507). `send_interval = chunk/rate/2` (463), so audio is written at 2x real time: Exotel can hold seconds of unplayed audio, and only a working `clear` drops it. Chunk is 4 x 10 ms = 640 bytes at 8 kHz (`base_transport.py:69`, `base_output.py:135`). Exotel's article says a minimum of 3.2 kB (100 ms); **UNVERIFIED** whether that matters here. |
| Pipecat `transports/base_output.py` | 55, 667-706, 732 | `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame` are broadcast both directions, so the user aggregator sees them (`MinWords` relies on it). Bot-stopped fires after 0.35 s of silence. |
| Pipecat `turns/user_turn_controller.py` | 171-179, 280-298, 314-337 | Start strategies run in order and the loop **breaks at the first STOP** (171-174). `_trigger_user_turn_start` ignores a second start while `_user_turn` is true (283-285). Stop and inference triggers are ignored when no turn is active (303-306, 318-319). |
| Pipecat `turns/user_start/min_words_user_turn_start_strategy.py` | 94-121 | Counts `len(frame.text.split())` against `min_words` while the bot speaks (105-108). One word ("wait", "ruko", "nahi") never reaches 2; "theek hai" does. It returns STOP on a trigger and calls `trigger_reset_aggregation()` otherwise (119). So the stock strategy cannot do this job. |
| Pipecat `turns/user_start/base_user_turn_start_strategy.py` | 120-132 | The two hooks I need: `trigger_user_turn_started()` and `trigger_reset_aggregation()`. |
| Pipecat `processors/aggregators/llm_response_universal.py`, user side | 766-831, 1131-1153, 1193-1212, 1277-1281 | A final `TranscriptionFrame` is appended to `_aggregation` (1149) **before** the controller sees the frame (829), whether or not a turn is running. `_on_reset_aggregation` calls `reset()` (1277-1281), which wipes it. A turn start with `enable_interruptions` calls `broadcast_interruption()` (1209-1210). Interim frames are not aggregated (794-798). |
| Same file, assistant side | 1482-1489, 1595-1612, 1641-1643, 1935-1956, 2055-2077 | `InterruptionFrame` calls `_trigger_assistant_turn_stopped(interrupted=True)`, which calls `push_aggregation()` and adds an assistant message. |
| Pipecat `services/tts_service.py` | 1127-1139 | For a service without word timestamps (ours: `ElevenLabsHttpTTSService`) the `TTSTextFrame` is pushed per synthesized sentence, not per spoken word. **UNVERIFIED** against playback timing. |
| Pipecat `audio/vad/vad_analyzer.py`, `silero.py` | 18-21, 162-163, 189-240; 190-196 | Defaults confidence 0.7, start 0.2 s, stop 0.2 s, min volume 0.6. At 8 kHz a window is 256 samples = 32 ms, so `start_secs=0.2` is 6 windows = 192 ms (my arithmetic, not a measurement). VAD runs inside the user aggregator and also decides turn end when listening. |
| Whole worktree grep | n/a | No existing use of `barge` or `MinWords` in `agent/`. `COPY *.py ./` (Dockerfile:65, from 014) ships any new `agent/*.py`. |

### Settled: does Pipecat 1.5.0 keep the bot's interrupted text?

**Yes, it keeps whatever text had already been pushed.** Reading: `_handle_interruptions` (1641-1643) commits before it resets. Test: a scratch script feeds a real `LLMContextAggregatorPair` assistant side through `pipecat.tests.utils.run_test`.

- Script: `/private/tmp/claude-501/-Users-vansh-Desktop-SALES-AGENT-nxlyr/4c6dc6d6-cd4f-40bf-b92e-b990e903cd73/scratchpad/interrupt_probe.py` (not in the repo).
- Result, run on this machine: text pushed then `InterruptionFrame` gives `[('assistant', 'Sentence one. Sentence two is long.')]`; nothing pushed gives `[]`.
- What this does not settle: because the HTTP TTS pushes text per sentence, the committed text can be **more** than the caller heard. How far ahead, on a real call, is **UNVERIFIED**. It matters because the model then believes it said things the caller never heard. This task pins the Pipecat behaviour in a test (A8) and does not change it.

## Design (files to touch and why)

### Files in scope

| File | Change | Why |
| --- | --- | --- |
| `agent/bargein.py` (new) | Word lists + `classify()`, `SmartBargeInStartStrategy`, `BargeInTrace`, `BargeInObserver`, `DualKeyExotelSerializer`, `SMART_VAD_PARAMS` | One new module keeps the `bot.py` hunks small and keeps this task's hunks away from 021's. |
| `agent/convo_config.py` | Add `bargein_mode` {legacy, smart}; add it to `log_line` | Same switch mechanism as 018/019. Redis, no deploy. |
| `agent/bot.py` | Imports (92-100 region); `build_user_turn_strategies` start list (221-224); `_build_user_aggregator_params` VAD params (262-269); serializer (442-451), observer added at 594-606 | The only wiring. Hunks stay in turn strategies, VAD, serializer and observers. Does not touch 469-504 (STT, LLM) or the greeting. |
| `agent/test_bargein.py` (new) | Tests A1-A8 | New test module. |
| `agent/test_convo_config.py`, `agent/test_turn_release.py` | Update exact-string and strategy-list assertions only where the new fields force it | Existing tests must stay green. |
| `AGENTS.md` (Commands) | Add `agent.test_bargein` to the unittest list and update the count | Rule in AGENTS.md: fix the Commands section. |
| `docs/memory/inbox/` | One note per learned fact | Memory rule. |

Not touched: `server.py`, `tools.py`, `prompt.py`, `voice_config.py`, `stt_keyterms.py`, `supabase/`, `infra/`, `dashboard/`.

### 1. `convo:config` field

- `bargein_mode`: `legacy` (default) | `smart`. Invalid value: warning, default (existing `parse` behaviour).
- `log_line` prints it, so every call's start line shows which mode it ran in.
- Task 021 also adds a `convo:config` field. Whoever merges second rebases `convo_config.py` (`_ALLOWED`, `_DEFAULT_RAW`, `ConvoConfig`, `parse`, `log_line`); the two additions are independent lines.

### 2. The strategy (`SmartBargeInStartStrategy`)

One strategy replaces **both** stock start strategies in smart mode. Do not stack it behind `VADUserTurnStartStrategy`: the controller stops at the first strategy that returns STOP (`user_turn_controller.py:171-174`), and a VAD strategy placed first would interrupt before ours ran. Do not place it first with a stock strategy behind it either, for the same reason in reverse, and because a started turn blocks a second start (283-285).

State: `bot_speaking` (from `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame`), `greeting_done`, `vad_started_at`, and the latest transcript for this speech burst.

**Bot not speaking: identical to legacy.** `VADUserStartedSpeakingFrame` and any interim or final transcript call `trigger_user_turn_started()` and return STOP, exactly as the two stock strategies do (`vad_user_turn_start_strategy.py:31-33`, `transcription_user_turn_start_strategy.py:38-43`). Turn latency does not move.

**Bot speaking:**

| Input | Action |
| --- | --- |
| `VADUserStartedSpeakingFrame` | Record the time and arm the sustained-speech timer. Never interrupts. |
| Interim or final transcript, zero words | Ignore. Log `kind=no_words` once per burst. |
| Transcript containing a stop word or phrase | `trigger_user_turn_started()` at once, on the interim if possible. |
| Two or more words that are not agreement words | Interrupt at once. |
| Only agreement words | Ignore. On a **final**, call `trigger_reset_aggregation()` so the words never reach the model. Interims are not aggregated, so nothing to wipe. Log `kind=agreement`. |
| Exactly one non-agreement word | Interrupt when it becomes a **final** transcript, or when the sustained timer fires, whichever is first. See open question 2. |
| Sustained speech: `now - vad_started_at >= 0.85 s` and at least one non-agreement word seen | Interrupt. Log `cause=sustained`. |
| `VADUserStoppedSpeakingFrame` with no interrupt | Clear the burst state. If nothing was heard, log `kind=no_words`. |

Classifier order (pure function, no I/O, so it is testable without Pipecat): normalise (lowercase, Unicode NFC, strip punctuation and hyphens inside "mm-hmm"); match stop words and phrases anywhere; then strip agreement phrases greedily (longest first, so "theek hai" and "thik hai" go as units); count what remains. Stop list from the decision plus "and similar": wait, stop, hold on, ruko, ek minute, nahi, no, actually, sorry, excuse me, sunno, plus Devanagari रुको, एक मिनट, नहीं, सुनो, रुकिए. Agreement list: haan, haanji, ha, accha, theek hai, thik hai, hmm, mm-hmm, ok, okay, yes, ji, right, sure, plus Devanagari हाँ, हां, हाँ जी, जी, अच्छा, ठीक है, हम्म, ओके. "theek" or "thik" alone also counts as agreement, because Deepgram can finalize half of "theek hai". The frozen lists go to the founder for review in the PR.

**Greeting protection (recommended, open question 1).** Until the first `BotStoppedSpeakingFrame`, the sustained and lone-word rules are off and "hello", "hi", "namaste" count as agreement words. Stop words and two or more non-agreement words still interrupt. One constant, `GREETING_PROTECT = True`, so the founder's answer is a one-line flip.

**Leaning toward interruption at the edges (LiveKit idea).** Once `BotStoppedSpeakingFrame` has fired, the strategy is back in "bot not speaking" and any transcript starts a turn, so nothing at the end of her turn is filtered (a test pins it, A2). I added no further start-of-turn bias beyond the greeting rule; the evidence for one is in LiveKit's design, not in our logs.

### 3. Serializer (`DualKeyExotelSerializer`, smart mode only)

Smart mode only (founder, 2 Nov); if the exit test shows it removes the tail, a follow-up task makes it the default. Subclass of `ExotelFrameSerializer`. On `InterruptionFrame` return `{"event":"clear","stream_sid":sid,"streamSid":sid}`. On audio frames, call `super().serialize()` and add `stream_sid` next to `streamSid` in the JSON (a parse and dump of a ~900-byte string per 40 ms; microseconds, no I/O, so no F06 concern). Everything else is the parent's. It stamps `trace.t_clear` when it serializes the `InterruptionFrame`, which is a few microseconds before `client.send`.

Smart-only keeps `legacy` byte-for-byte identical to today, so the legacy calls are a real control

### 4. VAD (smart mode only)

`SileroVADAnalyzer(params=SMART_VAD_PARAMS)` with `SMART_VAD_PARAMS = VADParams(confidence=0.75, min_volume=0.68)`; `start_secs` and `stop_secs` stay at 0.2. In smart mode VAD no longer interrupts, so this only affects the sustained timer and noise statistics. VAD also ends turns while listening, so the founder set a bar: **if first-sentence p50 rises by more than 30 ms in smart mode, the tightening is dropped.** Merge comes before the exit test (merge = deploy), so that cannot be measured before merge. Smart mode is off by default, so merging with the tightening in is harmless to every caller. If the exit test breaks the bar, the fix is a one-line follow-up PR setting `SMART_VAD_PARAMS` to Silero's stock values, done before smart mode is left on.

### 5. Measurement (`BargeInTrace` and `BargeInObserver`)

The observer works in **both** modes, so the legacy control is measured the same way. It sees frames with `on_push_frame` like `CallTimingObserver`. Per interruption it logs one line when the clear is serialized:

`barge-in: conn=<id> mode=<legacy|smart> cause=<legacy_vad|stop_word|multi_word|lone_word|sustained|transcript> t_vad_ms=0 t_fire_ms=<n> t_clear_ms=<n>`

Offsets are milliseconds after `VADUserStartedSpeakingFrame` (the VAD start; the voice itself began about 190 ms earlier, see VAD row). `t_fire` is when the `InterruptionFrame` first passes the user aggregator; `t_clear` is the serializer stamp. If no VAD start preceded the interruption (transcript-only), `t_vad_ms=-`.

Per ignored burst: `barge-in ignored: conn=<id> kind=<agreement|no_words|single_word_pending> words=<n>`. Word count and kind only, never the words (the log-hygiene rule from 004). The strategy and the observer share one `BargeInTrace` object created in `run_bot`, so there is no module-level state and two concurrent calls cannot mix.

What this cannot measure: how long the caller hears audio after the clear is sent, because Exotel's playout buffer is not visible to us. That stays a stopwatch, now as a cross-check of the logged numbers rather than the only measurement.

### Alternatives rejected

- `MinWordsUserTurnStartStrategy(min_words=2)` plus the transcription strategy: misses one-word interruptions ("ruko") and fires on "theek hai" (`min_words...py:105-108`).
- Stacking a word strategy after a VAD strategy: never reached (`user_turn_controller.py:171-174`).
- Interrupting on VAD and cancelling when the transcript turns out to be a backchannel: the bot has already stopped audibly; this is the bug.
- A longer VAD `start_secs` alone: delays real interruptions as much as it filters noise, and still lets "haan" through.

## Data touched (tables and columns; never execute SQL)

- Supabase: none. No table, column or migration.
- Redis `convo:config` hash: reads one new field, `bargein_mode`. The human sets it with `HSET` (no deploy, no secrets). Nothing new is written by the agent.
- Logs: two new line shapes (above). Neither carries transcript text, phone numbers or tokens.

## Acceptance tests (automated)

Run with the full list in AGENTS.md plus `agent.test_bargein`. No network, no live service, no sleeping: the strategy takes an injectable clock like the `FakeClock` in `test_turn_release.py`.

- A1 **Classifier table.** Every phrase in the decision, in Latin and Devanagari, with and without punctuation and case changes: stop words give INTERRUPT, agreement words (alone, repeated, "accha theek hai", "haan haan ji") give IGNORE, "what is the price" gives INTERRUPT, "price" gives LONE_WORD, "" gives NO_WORDS, "theek" alone gives IGNORE. A test asserts the frozen lists still contain each word the founder named.
- A2 **Strategy through a real `UserTurnController`** (as `test_turn_release.py` does): bot speaking, VAD start only gives no `on_user_turn_started`, and VAD stop gives no turn stop; "haan" final gives no start and one `on_reset_aggregation`; "wait" interim gives a start; "ruko" interim gives a start; "what is the price" gives a start; "accha theek hai" gives no start and a wipe; a lone word gives a start on its final; sustained speech with the fake clock gives a start at 0.85 s only if a non-agreement word was heard; bot not speaking gives a start on VAD alone and on a transcript alone (parity with legacy); a final right after `BotStoppedSpeakingFrame` starts a turn; during the greeting the sustained and lone-word rules are off but "wait" still interrupts.
- A3 **Aggregation wipe** on a real `LLMUserAggregator` through `pipecat.tests.utils.run_test` (the builder tries this first; if the harness cannot drive it, fall back to a direct `reset()` assertion and say so in the PR): after "haan", the context holds no user message and no LLM run is triggered.
- A4 **Serializer.** `InterruptionFrame` gives JSON with `event=="clear"` and both keys equal to the stream id; an audio frame gives both keys and a `media.payload` equal to the parent's; the trace gets `t_clear` set; an unrelated frame gives `None` as the parent does.
- A5 **Observer and log hygiene.** From fake frames, the exact `barge-in:` and `barge-in ignored:` lines; offsets are non-negative and ordered; no transcript text appears in any line (assert on a transcript like "haan ji 9876543210"). Extend the existing log-hygiene check if it enumerates line shapes.
- A6 **Config.** `parse()` on valid, invalid and missing `bargein_mode`; it appears in `log_line`. Existing exact-string tests updated.
- A7 **Legacy parity.** `build_user_turn_strategies` in legacy mode returns exactly `[VADUserTurnStartStrategy, TranscriptionUserTurnStartStrategy]`, both with interruptions on, and the same stop strategies as today; legacy VAD params equal Silero's defaults; legacy uses the stock `ExotelFrameSerializer`. Existing `test_turn_release.py` assertions stay as they are.
- A8 **Pinned Pipecat fact.** The assistant aggregator commits pushed text on `InterruptionFrame` (the scratch probe turned into a test). It fails loudly if a Pipecat upgrade changes this, which would change what the model believes it said.
- A9 **Import smoke** per AGENTS.md: `(cd agent && "$PY" -c "import server, week2_latency_observer")` passes. `requirements.txt` is unchanged.

## Exit test (what I do by hand, with exact commands)

Order matters; the control comes after, not before, so a bad smart build can be stopped early.

0. 👀 VERIFY, before merge: PR has the 10 headings, review by a different model recorded, unit tests pasted.
1. 🧑 YOU merge (merge = deploy). Default is `legacy`, so nothing changes yet. 👀 VERIFY the first call after the deploy is cold; do not count it.
2. 🧑 YOU switch on, on the VPS. This adds one field and leaves `prompt_version`, `stt_*` and `greeting_tags` alone. Do **not** use `DEL convo:config`; it would revert those.
   ```
   docker compose exec -T redis redis-cli HSET convo:config bargein_mode smart
   docker compose exec -T redis redis-cli HGETALL convo:config
   ```
3. 🧑 YOU place 6 calls in smart mode the way you placed the 018 and 019 exit calls: calls 1-3 with the phone at the ear, calls 4-6 on speakerphone with a fan running. On each call, ask for something that gets a long answer (the payment plan or the location), and during that answer do these six, one per answer, in this order, waiting for her to finish between them:
   1. cough
   2. "haan"
   3. "accha theek hai"
   4. "wait"
   5. "ruko"
   6. "what is the price"

   That is 36 events. Say them as you would on a real call, not louder.
4. 🧑 YOU score each event by listening, into a table with columns call, place (ear or speaker), event, did she stop (Y/N), did she answer the backchannel as if it were a question (Y/N). Expected: events 1-3 do not stop her and are not answered; events 4-6 stop her and she responds to them.
5. 👀 VERIFY the logged times. Read only the new lines, nothing else, and do not paste raw logs:
   ```
   docker logs nxlyr_agent 2>&1 | grep -E "convo config|barge-in"
   ```
   Check: each smart call shows `mode=smart`; every real interruption has one `barge-in:` line with `t_fire_ms` and `t_clear_ms`; each ignored backchannel and cough has a `barge-in ignored:` line; no line contains any words from the call.
6. 🧑 YOU run the control: 2 calls with the field removed, one at the ear and one on speaker with the fan, the same six events.
   ```
   docker compose exec -T redis redis-cli HDEL convo:config bargein_mode
   ```
   Legacy calls still log `barge-in:` lines (`mode=legacy`), so the three-timestamp comparison is like for like.
7. 🧑 YOU stopwatch two "wait" interruptions per mode as before (from your "wait" to her last word), to compare with the 0.5 s (plus or minus 0.3 s) you measured on 25 Oct and with the logged `t_clear_ms`.
8. 🧑 YOU `HDEL` the field again if you do not want smart mode to stay on, or leave it on.

**Proposed pass criteria (my numbers; change them if you disagree):**

| Measure | Smart (18 ignore events, 18 interrupt events) | Legacy control |
| --- | --- | --- |
| False stops (events 1-3 that stopped her) | at most 2 of 18, none for "haan" or "accha theek hai" at the ear | expected to be high; this is the baseline |
| Missed interruptions (events 4-5, "wait" and "ruko") | 0 of 12 | n/a |
| Missed interruptions (event 6) | at most 1 of 6 | n/a |
| Backchannel answered as if it were a question | 0 | n/a |
| Logged `t_clear_ms - t_fire_ms` | median at most 100 ms | reported |
| Logged `t_fire_ms` for stop words | reported, no limit (see latency risk) | reported |
| Leak counts | 0, as defined in the 008 and 018 exit tests, plus no transcript text in the new lines | 0 |
| First-sentence wait p50 (listening-side check) | rise of at most 30 ms against the legacy calls; more than that and the VAD tightening is dropped (founder) | baseline |

If the caller still hears her talk on for well over 0.1 s after `t_clear`, the dual-key clear did not work and Exotel is not honouring it: stop and report, do not guess (rule 9).

## Risks and rollback

**Rollback, no deploy:** `docker compose exec -T redis redis-cli HDEL convo:config bargein_mode` returns every new call to today's behaviour. Code rollback is reverting the PR; merging it is the human's.

| Risk | Detail |
| --- | --- |
| **Real interruptions may get slower, not faster.** | Legacy interrupts on VAD start, about 190 ms after the voice begins. Smart interrupts when Deepgram's interim shows a stop word or two non-agreement words, which I expect to be later (the interim latency on our calls is **UNVERIFIED**; 018 measured only final transcripts, about 275 ms after the end of speech on the EU endpoint). The bet is that the 0.5 s tail is mostly Exotel playing buffered audio because `clear` is ignored, not VAD. The three logged timestamps exist to settle this; if `t_fire_ms` for "wait" is far above legacy, the goal "stops faster" fails and we report it rather than tune blind. |
| **A tighter VAD changes listening too.** | VAD also ends turns while the bot listens (011). Raising confidence to 0.75 and min volume to 0.68 can delay the start of a quiet caller or cut a soft word short, which breaks "nothing changes while listening". Founder's bar: a p50 rise above 30 ms drops it (see Design 4). Since the transcript now makes the interruption decision, it is probably redundant. |
| **The "thinking" gap is not covered.** | Between the end of the caller's turn and the first bot audio, `BotStartedSpeakingFrame` has not fired, so "bot speaking" is false and a cough still cancels the LLM, as today (**UNVERIFIED** what the caller then hears; it may be dead air). Out of scope; the fix is to define "busy" as "from turn end until bot stopped", at some cost to simplicity. |
| **A backchannel finalizing just after the bot stops.** | If "haan" finalizes after `BotStoppedSpeakingFrame` it starts a turn, as today. Tested (A2), accepted. |
| **Committed text can exceed what was heard** (see Settled). | Unchanged by this task. If the exit test shows the model repeating things the caller never heard after an interruption, that is a follow-up. |
| **Deepgram language and script.** | Today's en-IN output is Latin (e.g. "haan"). If 021 switches to multilingual, output may be Devanagari; both are in the lists, but the Devanagari lists are untested on a real call (**UNVERIFIED**). |
| **Exotel chunk size.** | We send 40 ms chunks; the article asks for at least 100 ms. Calls work today, so I leave it. If `clear` still behaves partially after the key fix, this is the next suspect. |
| **Conflict with 021.** | Both edit `bot.py`. My hunks: imports, 221-224, 262-269, 442-467 (serializer and transport params), 594-606 (observers). 021's are the STT block at 469-495. Whoever merges second rebases; `bargein.py` and the tests do not conflict. |
| **Word lists are heuristic.** | A real interruption that happens to be one unlisted word is caught by the lone-word rule on its final (a delay of the endpointing time, 300 ms). A backchannel I did not list ("bilkul", "correct") counts as one non-agreement word and interrupts; the fix is a list entry. |

## Open questions for me

All five were answered by the founder on 2 Nov and are built into the design above:

1. Greeting: soft protection ("hello", "hi", "namaste" do not interrupt; "wait" and two or more real words do).
2. Lone non-agreement word: interrupts on its final transcript.
3. Dual-key serializer: smart mode only; a follow-up makes it the default if the exit test shows it removes the tail.
4. RNNoise: out of this task, no new dependency now.
5. Pass bars: as proposed, plus the 30 ms first-sentence p50 rule. The word lists are reviewed in the PR.

Still out of scope, as stated: the thinking-gap cough.

## Steps

1. 🧑 YOU approved this spec (2 Nov).
2. 🤖 AGENT (Codex) builds in the worktree: `bargein.py` and A1 first, then wiring, then the rest of the tests. Small commits.
3. 🤖 AGENT runs the full test command from AGENTS.md and pastes the output.
4. 🤖 AGENT (Claude, a different model from the builder) reviews the diff with `/codex:review`-style cross-review and records it in the PR.
5. 🤖 AGENT writes the PR report with the 10 headings, including "Shortcuts and debt".
6. 🧑 YOU merge, then run the exit test above and paste the table and the `barge-in` lines in "Evidence".
7. 🤖 AGENT closes memory: inbox notes (the settled interrupted-text fact, the `stream_sid` result, the measured numbers), `hot.md` and `product.md` only if you say so.

## Builder / Reviewer

- Builder: codex
- Reviewer (must differ): claude
