# 021 — Multilingual: Aarya understands and answers in Hindi and Hinglish, and English calls stay exactly as they are

**Status: r2, approved by the founder on 2 Nov 2026 with the decisions in "Decisions (founder, 2 Nov)" below. Nothing is open; the Devanagari check (item B) was done by the founder on 2 Nov with corrections applied (decision 11). The founder starts the build in Codex. No code written.**
Worktree `../nxlyr-worktrees/021-multilingual`, branch `task/021-multilingual`, from `origin/main` at `3b545d7` (018, 019, 008 and the 020 close-out merged).
Builder: Codex (well over 50 lines of change). Reviewer: Claude (must differ). Antigravity is not used.
Covers: founder priority 1 (30 Oct); the Day 1 checklist's Hinglish A/B item; the Gurugram plan.

## Goal

A caller who speaks Hindi or Hinglish is understood and answered in the same mix. A caller who speaks English gets today's English, with no new delay. It is one switch, `language_mode`, in the `convo:config` hash:

- `en` (default, and what any missing, invalid or unreadable value gives): exactly today's behaviour. Same speech settings, same prompt text byte for byte, same log lines apart from one appended field.
- `hinglish`: Deepgram `nova-3` with `language=multi` (code-switching), plus the prompt addendum below, appended to the system prompt.

The greeting stays English. The knowledge base stays English; the model translates on the fly. The switch needs no deploy and is read once at call start, like the other `convo:config` fields.

What this task does **not** know yet, and the exit test answers: whether `multi` works on the EU host with key terms; whether `eleven_v4_turbo` speaks Devanagari well with the live voice; whether Hindi replies stay inside `max_tokens=160`. Each has a probe or a flag below.

## Non-goals

- No change to the greeting, to `CLOSING_PHRASE`, or to the eight fixed refusal and failure sentences in `commitments.py` (see decision 2). They stay English in both modes.
- No Hindi knowledge base and no KB schema change. No SQL.
- No change to turn release, VAD, barge-in, the serializer or the turn strategies. That is 022, which edits the same `bot.py`; this task's `bot.py` hunks stay in the Deepgram block, the `convo_config` read and the prompt build.
- No `language_code` sent to ElevenLabs, no TTS provider change, no pronunciation dictionary. If the probe says `language_code` is needed on v4 Turbo, it becomes a one-line follow-up (see Design, voice).
- No language detection by code, no per-turn switching of STT language, no language question to the caller. The model mirrors the caller; Deepgram `multi` does the code-switching.
- No public claim. Nothing on the landing page or in `product.md` says "Hindi" until the exit test passes and the founder says so (CONSTRAINTS rule 7).
- No new dependency. The two probe scripts use the venv's `websockets` (16.0) and `aiohttp`, both already installed. UNVERIFIED that both are pinned in `requirements.txt`; the builder checks.
- No change to the `stt_numerals`, `stt_region`, `stt_keyterms` or `greeting_tags` fields or their defaults.
- **No change to the English prompt text** (`prompt.py` v2 and v21 bodies). A live call on 27 Oct said "Your site visit is set for Thursday…" before the tool returned. 021 only makes the harness catch it (`claimed_without_tool` gains `set for`, `fixed for`, `scheduled for`, in both modes). **Follow-up task: add the same rule to the English prompt**, with its own A/B.

## Design (files to touch and why)

### What I read (and what I did not)

Line ranges are in this worktree at `3b545d7` and in the installed Pipecat 1.5.0 (`agent/venv` of the main checkout). Nothing was run against a vendor API, and no call was placed.

| Where | Lines | What it showed |
| --- | --- | --- |
| `agent/bot.py` `run_bot`, STT block | 469-495 | `convo_cfg = await read_convo_config()` (472). Settings dict: `model nova-3`, `language "en-IN"`, `smart_format`, `interim_results`, `endpointing 300`; `keyterm` added if `stt_keyterms`; `numerals` if `stt_numerals`. `region` and `base_url "api.eu.deepgram.com"` when `stt_region=eu`. Built as `STTCheckingDeepgramService`. **This is the only place `language` is set.** |
| `agent/bot.py` prompt build and logs | 530-563 | `build_initial_messages(project_kb, lead_source, version=convo_cfg.prompt_version)` (530-534); the greeting is `messages[-1]` (535); the `prompt v2:` line (551-556) and `log_line(convo_cfg, conn_id, ...)` (557-563). |
| `agent/bot.py` LLM | 289-291, 497-504 | `LLM_MODEL "gpt-4o"`, **`LLM_MAX_TOKENS = 160`**, temperature 0.75. Hindi in Devanagari costs more tokens per word than English; **not measured** (the sandbox has no `tiktoken`, and I added no dependency). If a Hindi reply hits 160 it is cut mid-sentence with no final punctuation (see Risks, R5). |
| `agent/convo_config.py` | 17-30; 33-42; 51-94; 97-127; 134-156 | `_ALLOWED` and `_DEFAULT_RAW` (one entry per field), the frozen `ConvoConfig`, `parse()` (unknown field: WARNING and ignore; invalid value: WARNING and default; overrides list), `read_convo_config()` (0.5 s Redis timeout, defaults on any failure), `log_line()`. `language_mode` is one more entry in each of these. |
| `agent/stt_keyterms.py` | 158-207; 60-92; 17; 95-155; 190-207 | `STTCheckingDeepgramService`. `_WORD = [A-Za-z0-9]+...` (17): **a Devanagari transcript counts as `words=0`**. `summarize_transcript` (150-155) builds `words= project= amount=`. `push_frame` (190-207) logs `stt check:` for every `TranscriptionFrame`. Class name must keep "STT" (`latency_report.py` line 110 matches it). `build_keyterms` (60-92): project, developer, city, sector, and `FIXED_TERMS` (crore, crores, lakh, lakhs, rupees, BHK), all Latin. |
| `agent/prompt.py` | 302-325; 328-356; 212-299; 14-37; 13 | `build_system_prompt(..., version)` picks a builder and returns the text; `build_initial_messages` wraps it and the English greeting. `[HOW IT SOUNDS]` is the last block of both versions (198, 274). `CLOSING_PHRASE` (13) is English. The two banned-opener lists are English only. |
| `agent/tools.py` | 221-231; 585-640 | `_fixed_result` speaks a fixed sentence by `TTSSpeakFrame(..., append_to_context=True)` and returns `run_llm=False`. `end_call` speaks `CLOSING_PHRASE` (620). |
| `agent/commitments.py` | 26-42 | The eight fixed sentences: `BOOKING_NOT_CONFIRMED`, `CALLBACK_NOT_PASSED_ON`, `PAST_TIME`, `PAST_DATE`, `TIME_UNUSABLE`, `OUTSIDE_HOURS`, `TOO_FAR`, `DATE_UNUSABLE`. All English. |
| `agent/prompt_harness.py` | 38-48; 80-90; 89-170; 175-215; 218-231; 234-245; 275-343 | `BOOLEAN_FLAGS` (10), `_first_sentence` (uses Pipecat's `match_endofsentence`), `_word_count` (`\b[\w']+\b`: **splits Devanagari words at vowel signs, so Hindi counts are inflated**), `reply_flags` (English regexes only: `claimed_without_tool` matches "booked", "put you down" and so on), `HarnessStats.add` (sentence split on `[.!?]` only), the arg parser, `parse_script`, and `get_reply` (streaming; does not record `finish_reason`). |
| `agent/test_prompt_v21.py` | 125-145 | `test_n00` pins the v2 prompt to a stored golden. `agent/test_prompt.py:368-369` (P11) asserts the English prompt contains no `rahi`, `karungi`, `raha`, `karunga`. Both stay green because `en` mode adds nothing. |
| **Pipecat** `utils/string.py` | 44-92 (set), 94-101, 125-183 | `SENTENCE_ENDING_PUNCTUATION` **contains `।` (60) and `॥` (61)** and `?`. `UNAMBIGUOUS_SENTENCE_ENDING_PUNCTUATION` is the set minus `. ! ? ; …` (99-101). `match_endofsentence` (125-183) asks NLTK first, and **falls back to the unambiguous marks when NLTK sees one sentence** (160-170). |
| **Pipecat** `utils/text/simple_text_aggregator.py` | 49-76; 78-121; 123-135 | `aggregate` goes char by char; `_check_sentence_with_lookahead` flags a sentence-ending mark, waits for the next non-space character, then calls `match_endofsentence`. `flush` returns the rest at end of stream. `services/tts_service.py:288` makes this the default aggregator. |
| **Pipecat** `services/deepgram/stt.py` | 552-609; 634-660; 686-709 (Language cast at 703-706); 182-215 | `_build_connect_kwargs` sends `language` as `str(...)` and lists (`keyterm`) as repeated params. `_on_message` does **`Language(language)` on `alternatives[0].languages[0]` with no guard (704-706)**; an unknown code raises `ValueError` inside the message handler. `_connection_handler` (634-660) catches an exception, logs "Connection lost, will retry" and loops. |
| **Pipecat** `services/elevenlabs/tts.py` | 53-61; 1348-1396 | `ELEVENLABS_MULTILINGUAL_MODELS = {eleven_flash_v2_5, eleven_turbo_v2_5}`. `run_tts` (HTTP) adds `language_code` to the payload **only if the model is in that set and `settings.language` is set** (1389-1396); otherwise it logs a WARNING and sends nothing. `eleven_v4_turbo` is not in the set. `previous_text` is sent for later sentences (1374-1375), as 019 found. |
| `agent/voice_config.py` | 18-24; 96-239 | `MODELS` allow-list contains `eleven_v4_turbo` and `eleven_flash_v2_5`. No `language` field; none needed in this task. |

**Things I ran** (scratchpad scripts, not committed, no network, no secrets):

1. `SimpleTextAggregator` fed one, three and 1 to 4 characters at a time with Hindi, Hinglish and English strings. Results in "Sentence splitting" below.
2. `Language("hi")`, `Language("en")`, `Language("hi-IN")` parse. `Language("hi-Latn")`, `Language("bho")` and `Language("xx")` raise `ValueError`.
3. `STTCheckingDeepgramService(settings=DeepgramSTTSettings(model="nova-3", language="multi", keyterm=[...], endpointing=300), region="eu", base_url="api.eu.deepgram.com")` builds, reports host `api.eu.deepgram.com`, and `_build_connect_kwargs()` gives `language='multi'`, `endpointing='300'`, the `keyterm` list and `smart_format='true'`. Pipecat logs a DEBUG line "Language string 'multi' is not a recognized Language code. It will be passed to the service as-is." That proves what we send, **not that Deepgram accepts it**.

**Not run, UNVERIFIED:** any request to Deepgram or ElevenLabs; what Deepgram returns for Hindi (script, `languages` codes); whether Smart Turn v3 handles Hindi (the installed `smart_turn` code names no languages); how GPT-4o's token count compares for Hindi; how ElevenLabs reads Latin words inside Devanagari text.

### Vendor claims, with sources

"Fetched" means I read the page on 2026-10-31 through a fetch tool that summarises the page. None of these pages shows a page date. The changelog entries show model versions, not publication dates. The builder re-reads each page before the PR cites it.

| # | Claim | Source (fetched 2026-10-31) | Status |
| --- | --- | --- | --- |
| V1 | `language=multi` is served by Nova-2, Nova-3, Nova-3 Medical and Flux Multilingual (`flux-general-multi`, a different model id). | https://developers.deepgram.com/docs/multilingual-code-switching | Docs. Not tested. |
| V2 | **`model=nova-3&language=multi` now serves a new multilingual model: 55 languages, one model.** The previous 10-language model (English, Spanish, French, German, Hindi, Russian, Portuguese, Japanese, Italian, Dutch) can be pinned with the `version` parameter: streaming `2026-01-27.9249`, batch `2026-01-27.9107`. A new optional `language_hint` parameter applies only with `language=multi`. The entry names `api.deepgram.com` only, mentions no region, and says nothing about key terms. | https://developers.deepgram.com/changelog/2026/10/23.md (the entry carries no date; the search result file name is `2026/10/23`) | Docs. **This changed 8 days before this spec.** Whether Hindi is in the 55 is the entry's link to the language overview; the 10-language model contains Hindi. |
| V3 | **Hindi (`hi`) is a supported Nova-3 language.** The overview page lists Hindi as monolingual. It lists `multi` under `nova-3-medical` (with Hindi), and it did not show a `multi` row for plain `nova-3` in the extract I read, though V1 and V2 say Nova-3 does. Hinglish (`hi-Latn`) is listed only for legacy Nova and Base, **not Nova-3**. | https://developers.deepgram.com/docs/models-languages-overview | Docs, internally inconsistent in my read. The probe settles it. |
| V4 | Deepgram recommends `endpointing=100` for code-switching. We use 300 (see decision 3, stays 300). | https://developers.deepgram.com/docs/multilingual-code-switching | Docs. |
| V5 | **Key terms:** "available for both monolingual and multilingual transcription using the Nova-3 Models"; limit 500 tokens per request; suggests 20 to 50 terms. Ours is at most 10 terms in practice (`MAX_TERMS` 40, 400-token estimate). The page does not name `language=multi`, and the 23 Oct changelog entry does not mention key terms. | https://developers.deepgram.com/docs/keyterm | Docs say yes. **UNVERIFIED for the new 55-language model on the EU host.** |
| V6 | EU endpoint is `api.eu.deepgram.com`, covers Speech-to-Text, and serves Nova and Flux models (Whisper excluded). **No page I found says that `language=multi` is served there.** | https://deepgram.com/blog/deepgram-eu-endpoint-now-generally-available and the data-residency page https://developers.deepgram.com/trust-security/your-data (not fetched directly; seen in search results) | **UNVERIFIED for `multi` on the EU host.** The probe answers it. |
| V7 | Hindi output script (Devanagari or Latin) for `multi`: **no page says.** The 23 Oct entry says words carry a `language` tag and alternatives carry `languages`, either of which "may be absent on code-switched audio". | same pages | **UNVERIFIED.** The probe prints it. |
| V8 | ElevenLabs Eleven v4 Turbo: "90+ languages supported", Hindi (`hi`) included, median latency about 100 ms. Flash v2.5: 32 languages, Hindi included. Multilingual v2: 29 languages, Hindi included. | https://elevenlabs.io/docs/overview/models | Docs. **Founder's web-app test (2 Nov, reported, not reproduced here): `eleven_v4_turbo` with Devanagari Hindi was clearly best.** The live voice is now `9lx2GDtpvyyNBM7O9Mmx`; the probe in exit step 2 repeats the test with that voice. |
| V9 | `language_code` on the stream-with-timestamps endpoint: "Language code (ISO 639-1) used to enforce a language for the model and text normalization"; "not supported for multilingual_v2 models"; if a model does not support the code it is ignored, not rejected. Without it the model works from the text. | https://elevenlabs.io/docs/api-reference/text-to-speech/stream-with-timestamps | Docs. Enforcing a language also forces that language's text normalisation, which would be wrong for English sentences in an English call. We do not send it (Voice, below). |

### Speech recognition (`agent/bot.py` Deepgram block, `agent/stt_keyterms.py`)

**bot.py, lines 469-495 only.** After `convo_cfg = await read_convo_config()`:

- `"language": "multi" if convo_cfg.language_mode == "hinglish" else "en-IN"`. Every other setting is untouched: `endpointing` stays 300, `smart_format` and `interim_results` stay, `stt_keyterms`, `stt_numerals`, `stt_region` keep working exactly as now.
- Key terms stay on in hinglish mode **if the probe shows `multi` accepts them on the host in use**. The terms are all Latin (project, developer, city, sector, crore, lakh, rupees, BHK), which is how they would be said inside a Hindi sentence.
- **Decided (Q3/Q4, founder 2 Nov), two independent fallbacks, both applied in hinglish mode only; English mode keeps today's settings.** (i) If the probe shows `multi` is **not served on the EU host**, hinglish calls use the **global host** (about 85 ms slower, accepted); `stt_region` stays what it is for English. (ii) If the probe shows **key terms are rejected with `multi`** (on whichever host), `keyterm` is dropped in hinglish mode only, and the v21 prompt rule that takes a near-miss project name as the project (`prompt.py` 247) carries that load. The probe's four rows decide both. Each is a small `if` in the same block, keyed on the probe result written into the PR, not on a runtime check. I do not recommend pinning the old model with `version`: it is a stopgap Deepgram may retire, and I have not checked that Pipecat 1.5.0 can pass `version` (UNVERIFIED).
- **Fail-loud guard, because a rejected parameter silences the call.** Pipecat's `_connection_handler` (634-660) swallows a failed connect and retries forever, and the caller hears nothing. The same class of failure as the v4 `previous_text` risk in 019. The guard is procedural, not code: exit test step 1 runs the probe for the exact combination before any call, and the probe prints the connect result. Code only gets the next change.

**stt_keyterms.py, three small changes:**

1. **Unknown language codes must not drop a transcript.** `STTCheckingDeepgramService` overrides `_on_message(message)`: before calling `super()`, if the result's first alternative has a `languages` list whose first code is not a valid Pipecat `Language`, set that list to `None`/empty on the message so Pipecat pushes the transcript with `language=None`. Nothing else changes. Why: with `multi`, Deepgram tags languages per result, Pipecat parses the first with `Language(...)` unguarded (703-706), and `Language("hi-Latn")`, `Language("bho")` and any code outside the enum raise `ValueError` in the handler. What the SDK does with an exception in a message callback is UNVERIFIED; at best the transcript is lost, at worst the connection restarts. In `en-IN` mode the codes are English and cannot trigger it.
2. **`stt check:` shows what was heard, in hinglish mode only.** `summarize_transcript(text, project_name, *, hinglish=False)` keeps the existing `words= project= amount=` fields. When `hinglish=True` it (a) counts `words` by whitespace so a Devanagari transcript is not `words=0`, and (b) appends `script=deva|latin|mixed|none` (share of Devanagari letters: at least 0.8 `deva`, at most 0.2 `latin`, otherwise `mixed`) and `lang=<first code Deepgram returned, or none>`. No transcript text is logged, as today. The English line is **byte-identical** to today's (a test pins it).
3. **`stt endpoint:` line gains `language=<value>`** (`en-IN` or `multi`), for both modes, so the log states what the call asked Deepgram for. Pipecat logs no connect URL, and the exit test needs this. This is the one appended field in English mode; tests that match that line are updated.

### Conversation switch (`agent/convo_config.py`)

One new field, `language_mode`, `en | hinglish`, default `en`, in `_ALLOWED`, `_DEFAULT_RAW`, `ConvoConfig` (`language_mode: str = "en"`), `parse()`'s return, and `log_line()`. Same reader (`read_convo_config`, 0.5 s), same fallback (absent, invalid or unreadable gives `en`, WARNING `Invalid convo:config value for language_mode; using default`), same single log line, which gains `language_mode=<en|hinglish>` between `greeting_tags=` and `read_ms=`. `stt_region`'s existing tests are the model.

### Prompt (`agent/prompt.py`: an addendum only, plus a keyword argument)

`build_system_prompt(..., language_mode="en")` and `build_initial_messages(..., language_mode="en")` gain one keyword argument. When it is `"hinglish"`, `build_system_prompt` returns `builder(...) + "\n\n" + HINGLISH_ADDENDUM`. When it is `"en"` the function returns exactly what it returns today (the v2 golden test and every v21 test stay untouched and green). The addendum goes **last**, after the knowledge base and the samples, so it is the freshest instruction and cannot be read as part of the KB JSON. It is appended to both prompt versions; it is written against v21 (the live one), and v2 plus hinglish is allowed but not exercised. The greeting and `plain_greeting` are untouched. `bot.py` passes `language_mode=convo_cfg.language_mode` in the existing `build_initial_messages(...)` call (530-534), and adds `language_mode=` to the `prompt v2:` line (551-556) so the prompt and the config line cannot disagree.

#### The prompt addendum, verbatim (for line-by-line approval)

Everything between the two rules is the text, character for character. It is one block of 15 lines and 3,710 characters (measured), 225 of them Devanagari. It contains Devanagari; **the founder checked every Devanagari phrase on 2 Nov 2026 and corrected five items (decision 11); this is the corrected text.**

---
```
[LANGUAGE]
Callers may speak English, Hindi, or a mix of both in one sentence. You understand all three. The rules in this block come on top of every rule above; where they differ, follow this block.
- Mirror the caller. Reply in the language mix of the caller's latest message. If the caller spoke only English, reply only in English. If the caller spoke Hindi or a mix, reply in the same mix. If the mix changes, change with it. Never switch on your own, and never ask the caller which language they prefer. If the caller asks you to speak in one language, use it from then on until they ask for another.
- The caller's words reach you as text. Hindi may arrive in Devanagari or in Latin letters. Treat both as Hindi, and reply in Devanagari.
- Write Hindi words in Devanagari. Write English words in Latin letters: project names, sector names, brand names, "BHK", "Next Layer", "AI", and English words callers already use inside Hindi, such as "site visit", "payment plan" and "budget". Never write Hindi in Latin letters. Never write an English word in Devanagari.
- You are a woman. Every verb that says what you do, say or know takes the feminine form: "मैं बता सकती हूँ", "मैं समझ गई", "मैं देख रही हूँ". Never use the masculine form, such as "बता सकता हूँ".
- Say "आप" to the caller. Never "तुम" or "तू". You still never use a name for the caller and never say "सर" or "मैडम".
- Numbers, amounts, areas, percentages, counts, day names, month names, dates and times are said in English words, in Latin letters, as people in Gurugram say them. Hindi is only for the connecting words around them. Never use a Hindi number word, day name or month name: say "Saturday", "November", "three BHK", "eleven बजे" or "eleven in the morning". Relative days are English too: "today", "tomorrow", "day after tomorrow". The article "एक" (a) is fine. Never digits, never "₹" and never "Rs". Say an amount or an area exactly as the knowledge base's "spoken" line says it, as one unbroken phrase, such as "two point two crore rupees". Change only the words around it. Never convert, round or recompute a figure. When the caller gives a day or time in Hindi, say it back in English words: "Saturday को eleven बजे ठीक रहेगा।"
- The knowledge base is in English. Translate its facts into the caller's language and keep every name, figure and unit as it is. If you lack a fact, say so in one sentence in the caller's language. Never invent one.
- Every sentence ends with punctuation. End a Hindi sentence with "।" and a question with "?". End an English sentence with "." or "?". Put a space after it. Never end a reply without punctuation.
- Keep the length rules above. In Hindi too, the first sentence is eight words or fewer.
- Do not open a reply in Hindi with "बिल्कुल", "ज़रूर", "ठीक है", "समझ गई", "अच्छा" or "ग्रेट". A short "जी," is fine, but never in two replies in a row.
- Where the rules above give a fixed line, say its Hindi form when the caller is speaking Hindi. If the caller only greets you: "जी, मैं यहाँ हूँ।" If they check you are there: "जी, आपकी आवाज़ आ रही है।" If you did not catch what they said: "माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया।"
- If the caller asks in Hindi whether you are an AI, a bot or a person, answer at once and truthfully: "जी, मैं एक AI assistant हूँ, Next Layer की तरफ़ से call कर रही हूँ।" Then carry on. Never deny it.
- Function arguments stay in English: notes in English, dates as YYYY-MM-DD, times as HH:MM. Never say a visit is booked, put down, noted or passed on in Hindi either, unless you called the function in that same reply or a function result has just said it is done. Hindi forms of that claim, such as "बुक कर दी", "नोट कर ली" and "पक्का कर दिया", count.
```
---

Three lines in it carry a choice you should look at: the **Numbers** line (decisions 1 and 9: every number, day, month, date and time in English words), the **Script** line (decision 10), and the **AI** line (corrected by the founder, decision 11), which repeats the 014 disclosure in Hindi (`on_ask` mode; the `upfront` mode text is not touched). The addendum adds 3,710 characters to a prompt that is 4,790 characters before the KB (014's measurement), so it is a large relative increase in input, roughly 1,100 tokens (an estimate; no tokenizer in the sandbox). It may add some first-token time; the control calls measure that. A test caps its length. The same addendum text is used by the harness, so what you read here is what runs.

### Sentence splitting (Pipecat 1.5.0): already works, pinned by a test, no fix

Question: does Pipecat's sentence-end detection recognise `।` and `?` after Devanagari? **Yes, by reading and by running it.** `।` is in `SENTENCE_ENDING_PUNCTUATION` (`utils/string.py:60`), and when NLTK sees only one sentence `match_endofsentence` falls back to the unambiguous marks (160-170). I fed `SimpleTextAggregator` the strings below one character, three characters and 1 to 4 random characters at a time. A sentence is released when the next non-space character arrives (the lookahead), exactly as with English:

| Input | Result |
| --- | --- |
| `जी, Eridian Heights में तीन BHK उपलब्ध हैं। कीमत एक पॉइंट दो करोड़ रुपये से शुरू होती है। आप कब आना चाहेंगे?` | Sentence 1 released after `।` and the first character of sentence 2; sentence 2 likewise; the last (`?`) at flush, same as English. |
| `आप कब आना चाहेंगे? शनिवार को ग्यारह बजे ठीक रहेगा।` (a splitting test string, not model output; the model now says "Saturday को eleven बजे") | `?` splits. Last at flush. |
| Hindi ending in `.` | Splits the same. |
| `Sector 65 में है, Gurugram में। Would you like a site visit? हाँ बोलिए।` | Three sentences, across scripts. |
| English `Sure. It starts at one crore. Want a visit?` | Unchanged. |
| `जी हाँ तीन BHK उपलब्ध हैं` (no mark) | **Nothing is released until flush: the whole reply reaches the voice at the end.** |
| `...हैं?हाँ बोलिए।` (no space after `?`) | One chunk at flush. |

So the large latency hit exists only when a reply has no sentence mark, or no space after it. That is why the addendum has the punctuation rule, the harness has a `no_final_punct` flag, and `finish_reason=length` is recorded (R5). **No code fix.** The test `L07` pins these cases so a Pipecat upgrade cannot silently change them.

### Voice (`eleven_v4_turbo` via `voice:config`; no code change)

- Docs say v4 Turbo and Flash v2.5 both cover Hindi (V8). Pipecat will **not** send `language_code` on v4 Turbo (the model is not in `ELEVENLABS_MULTILINGUAL_MODELS`, `tts.py:53-61`, gate at 1389-1396) and `voice:config` has no language field. Without it ElevenLabs works from the text, and every sentence is synthesised on its own, so an English sentence inside a Hindi call is read as English. Forcing `hi` would also force Hindi normalisation on English sentences. **Recommendation: send nothing; decide by ear.**
- Whether v4 Turbo with the live voice reads Devanagari naturally, and Latin words inside Devanagari (project names, "BHK", "two point two crore rupees"), is **UNVERIFIED** until the TTS probe (exit test step 2) and the Hinglish calls.
- If the probe says `language_code` improves Hindi on v4 Turbo, the follow-up is one line (`ELEVENLABS_MULTILINGUAL_MODELS.add("eleven_v4_turbo")` plus a `language` on the settings), which is a voice-side change outside this task.
- **Fallback:** `HSET voice:config model eleven_flash_v2_5`, no deploy. Flash v2.5 lists Hindi (V8). Cost: `greeting_tags` become `blocked` (v4 only; the plain greeting is used and the line says so), and 019's `previous_text` and settings rules for non-v4 models apply.
- The keep-warm request (019) is English `Hi.`; a Hindi-voice warm-up is not needed.

### Tools and the fixed sentences (008)

- **Success** replies are written by the model and follow the addendum (Hindi, with the amount rule), so they are covered. The tool result's `visit` and `next_step` strings stay English for the model.
- **The eight fixed sentences** in `commitments.py` and `CLOSING_PHRASE` are spoken by code, in English, in both modes. They are short, true and only on failure or refusal paths. Simplest honest option: **leave them in English in 021 and say so in the PR.** A Hindi caller hears one English sentence ("Sorry, I couldn't confirm that visit just now, so please don't count on it yet.") at the worst moment, which is a worse experience but never a false claim. Two alternatives, both rejected for now: (a) hand-written Hindi twins chosen by `language_mode` would be wrong for English callers in hinglish mode, and code does not know which language the last turn used; (b) routing the failure through the model would let it improvise a promise, which is exactly what 008 removed. See decision 2 (approved).
- The Telegram alert and the `call_commitments` row stay English (the addendum says notes are English).

### Number safety (the risk the model translates figures)

The KB holds figures as digits in many fields and as English words in the `spoken` lines (`prompt_scripts/kb_meridian_heights.json`: `pricing.spoken`, `unit_types[].spoken`, `payment_plan.spoken`). The inbox note `2026-10-24-kb-digits-read-aloud-crore-mispronounced.md` says the rest of the live KB still has digits. A model that turns "two point two crore" into Hindi number words can slip on the irregular Hindi numbers (for example twenty-nine, thirty-nine, sixty-nine) or confuse lakh and crore. Two defences:

1. **By construction (the Amounts line):** the model copies the figure phrase from the `spoken` line in Latin letters and translates only the words around it. It never forms a Hindi number word for a KB figure. This makes the check mechanical.
2. **A check in the harness:** flag `figure_not_in_kb`. It extracts runs of English number words and units from a reply (zero to ninety, hundred, thousand, point, lakh, crore, percent, and the bare digits) and reports any run that is not a substring of the KB's text (the harness KB, or `--kb live`). It is deliberately narrow: it catches a changed figure and misses a figure said in Devanagari words, which the `wrong_script` flag and the founder's ear cover. In the Hinglish calls every price, size, payment and possession answer is read against a printed figure card (exit test, step 6).

If Hindi number words were ever wanted (rejected in decision 1), defence 1 would go away and this check needs a Devanagari number table of about 100 entries; I would then ask for a second pass on the spec.

### Harness (`agent/prompt_harness.py`, `agent/prompt_scripts/`)

- New option `--language-mode en|hinglish` (default `en`), passed to `build_initial_messages`. In `en` mode the output is byte-identical to today's except that `claimed_without_tool` now also fires on `set for`, `fixed for` and `scheduled for` (a test pins a stored summary; the stored replies contain none of those phrases, which the builder confirms, and says so if one does).
- In `hinglish` mode only, `reply_flags` returns extra flags and the summary prints them on a second flags line:

| Flag | True when |
| --- | --- |
| `masc_verb` | The reply has a masculine first-person verb: `...ता हूँ/हूं`, `...रहा हूँ/हूं`, `...ूँगा/ूंगा/ऊँगा/ऊंगा`, `समझ गया`, in Devanagari, matched with Devanagari-aware boundaries (plain `\b` fails on vowel signs). The list is in code and in a test. |
| `digits` | Reuses the existing flag (digits, `₹`, `Rs`; Python `\d` also matches Devanagari digits). |
| `wrong_script` | A reply has a romanised Hindi function word (`hai, hain, hoon, aap, kya, nahi, haan, theek, bataiye, sakti, chahiye, baje, ...`, a closed list that avoids English look-alikes such as "main"), **or** a Devanagari rendering of a word that must stay Latin (`बीएचके`, `साइट विज़िट`, `पेमेंट प्लान`, `नेक्स्ट लेयर`). |
| `english_to_hindi` | The caller line has Devanagari or a romanised Hindi word, and the reply has no Devanagari at all and more than three words. |
| `hindi_to_english` (added by me) | The caller line is plain English and the reply contains Devanagari. This is the "English calls no worse" flag. |
| `no_final_punct` (added by me) | The reply does not end in `. ? ! ।`. Protects the sentence-splitting point above. |
| `claimed_without_tool` | Extended in **both modes** (one pattern list, no mode condition; decision 11). Today's English pattern (`prompt_harness.py:146`: `booked`, `put you down`, `down for`, `confirmed`, `noted`, `passed on`, `passed that on`, `passed it on`, `i've noted`) gains `set for`, `fixed for` and `scheduled for`. The Hindi claims are added: `बुक कर दी/दिया`, `नोट कर ली/लिया`, `पक्का कर`, `कन्फ़र्म`, `आगे बढ़ा दिया` and `सेट कर दी`. So the 008 invariant is checked in Hindi too, and a reply like "Your site visit is set for Thursday…" before the tool returns is caught. Cause: a live call on 27 Oct said exactly that before the tool returned. |
| `figure_not_in_kb` | See Number safety. |
| `hindi_calendar` (decision 9) | The reply contains a Hindi day name (`सोमवार, मंगलवार, बुधवार, गुरुवार, बृहस्पतिवार, वीरवार, शुक्रवार, शनिवार, रविवार, इतवार`), month name (`जनवरी, फ़रवरी/फरवरी, मार्च, अप्रैल, मई, जून, जुलाई, अगस्त, सितंबर/सितम्बर, अक्टूबर/अक्तूबर, नवंबर/नवम्बर, दिसंबर/दिसम्बर`) or relative day (`आज, कल, परसों`), matched with Devanagari-aware boundaries. Closed list in code and in a test; a spelling not on the list is missed. |
| `hindi_number` (decision 9) | The reply contains a Devanagari number word: `शून्य`, `दो` to `निन्यानवे` (the full 2 to 99 table including the irregular 21 to 99 forms and spelling variants such as `पाँच/पांच`, `छह/छः`), `सौ`, `हज़ार/हजार`, `लाख`, `करोड़`, `डेढ़`, `ढाई`, `सवा`, `पौने`, `आधा`. **`एक` is left out on purpose** because it is also "a" ("एक AI assistant"), so a Hindi "one" is missed; `दो` can also mean "give", which the model does not say to a caller it addresses as "आप". The table is long; it was covered by the founder's Devanagari check of 2 Nov (decision 11: everything else correct). |
| `truncated` (added by me) | The stream ended with `finish_reason == "length"`. `get_reply` records it. |

- `timing_word` and `generic_closer` get a few Hindi forms (`जल्द ही`, `अभी तुरंत`, `और कुछ जानना चाहेंगे`).
- `_word_count` splits on whitespace when a text contains Devanagari (Latin text keeps today's regex), so Hindi `first_sentence_words` is honest. `HarnessStats.add` splits sentences on `[.!?।]` as well. Neither changes English output.
- New caller-line scripts (H1 to H7 as before, where H1 and H7 now also test the English-words rule, plus a new H8 for relative days, months, dates and times), `agent/prompt_scripts/hinglish_v21.txt`, in the existing `parse_script` format (`---` between scenarios, `#` comments). Proposed content, for your review (the harness KB is Meridian Heights, as in `conversation_v21.txt`):

```
# H1 — Hindi in Devanagari, the 018 S1 steps in the same order. The caller says Hindi day, time and numbers on purpose;
# every reply must say them back in English words (flags hindi_calendar, hindi_number)
हाँ जी, बोलिए।
मैं अपने परिवार के लिए घर देख रहा हूँ, मेरे भाई पास में ही रहते हैं, और मुझे पज़ेशन की डेट और लोकेशन पक्के तौर पर जाननी है
मेरा बजट लगभग एक पॉइंट दो करोड़ है
Meridian Heights के बारे में बताइए
ये तो बहुत महँगा लग रहा है
पेमेंट प्लान क्या है?
क्या आप मुझे WhatsApp पर डिटेल्स भेज सकती हैं?
क्या मैं शनिवार को सुबह ग्यारह बजे आ सकता हूँ?
नहीं, शनिवार नहीं, रविवार को
मुझे किसी असली इंसान से बात करनी है
---
# H2 — Hindi in Latin letters, as Deepgram may return it
haan ji boliye
mujhe 3 BHK dekhna hai Sector 79B ke aaspaas, family ke liye
budget around two crore hai
price kya hai aur possession kab milega?
payment plan samjhaiye
kya main Saturday ko eleven baje site visit kar sakta hoon?
theek hai, thanks, bye
---
# H3 — code-switching inside one sentence, and an English opener
Hi Aarya.
Meridian Heights ka 3 BHK ka price क्या है?
और possession कब तक मिलेगा?
क्या वहाँ से Cyber City दूर है?
मुझे इसके बारे में सोचना पड़ेगा, family से बात करके बताता हूँ
bas itna hi, thank you
---
# H4 — English callers in hinglish mode (the 018 S1 lines; no Devanagari allowed in any reply)
Hi Aarya.
yes
my budget is around one point two crore
tell me about Meridian Heights
that sounds expensive
what's the payment plan?
can you WhatsApp me the details?
can I visit on Saturday at 11 am?
can I talk to a real person?
---
# H5 — the caller changes language and asks for one
tell me about the 3 BHK
अच्छा, और पज़ेशन कब मिलेगा?
okay, and the price?
Hindi mein hi bataiye
actually English is fine
---
# H6 — short pings, identity, disclosure
हेलो?
आप कौन बोल रही हैं?
कौन सी कंपनी से?
क्या आप रोबोट हैं?
क्या आप सच में इंसान हैं?
---
# H7 — unclear, cut off, and an amount with no unit
वो... मतलब... हाँ
मेरा बजट दो है
मेरा बजट अस्सी लाख है
---
# H8 — Hindi relative day, month, date, time and number words from the caller; the reply must use English words for all of them
कल शाम पाँच बजे आ सकता हूँ?
नहीं, परसों सुबह दस बजे
पंद्रह नवंबर को चलेगा?
तीन BHK में कितने बेडरूम हैं?
```

### Files in scope

| File | Change |
| --- | --- |
| `agent/convo_config.py` | `language_mode` field, parse, log. |
| `agent/bot.py` | Deepgram block (469-495): language. Prompt build (530-534) and the `prompt v2:` line (551-556): pass and log `language_mode`. `summarize_transcript` flag passed at STT construction. **Nothing else** (no turn strategy, serializer, TTS or LLM hunk; plus the hinglish-only `max_tokens` in the LLM block (497-504) if `truncated` is non-zero, decision 5). |
| `agent/stt_keyterms.py` | Guard, `stt check:` fields, `stt endpoint:` language field. |
| `agent/prompt.py` | `HINGLISH_ADDENDUM`, the keyword argument, the append. No existing text changes. |
| `agent/prompt_harness.py`, `agent/prompt_scripts/hinglish_v21.txt` | Option, flags, scripts. |
| `agent/test_convo_config.py`, `agent/test_stt_keyterms.py`, `agent/test_prompt_harness.py` | Existing assertions on the two log lines and the harness summary updated; new cases. |
| `agent/test_language_mode.py` (new) | The rest of the tests. Added to the AGENTS.md command (14 modules). |
| `scripts/probe_deepgram_multi.py`, `scripts/probe_elevenlabs_hindi.py` (new) | Exit test probes. Read keys from the environment; print status codes and counts; never print a key. |
| `AGENTS.md` | The unit-test command gains `agent.test_language_mode`; the count line is updated. |
| `docs/memory/inbox/` | One note per verified or refuted vendor claim (V2, V5, V6, V7, V9). |

Anything else needs your approval.

## Data touched

- **Supabase: none.** No table or column is read or written by the new code. No SQL file is written, none is run by an agent.
- **Redis, existing hash `convo:config`:** one new optional field `language_mode` (`en` or `hinglish`), written only by you with `HSET`/`HDEL`, read once per call by `read_convo_config()` (`HGETALL`, 0.5 s). No key is created by the code. No other Redis key changes.
- **Logs:** `convo config:` gains `language_mode=`; `stt endpoint:` gains `language=`; `stt check:` gains `script=` and `lang=` in hinglish mode only. All are enums or short codes: no transcript, no phone, no model text.
- **External calls (probes only):** Deepgram and ElevenLabs, with keys from your environment. An agent never sees a key (CONSTRAINTS rule 5).

## Acceptance tests (automated)

Run with the AGENTS.md command; all offline, no network, no live service. The 13 existing modules must still pass unchanged apart from the two pinned log-line assertions and the harness summary golden named above.

| ID | Test |
| --- | --- |
| L01 | `convo_config`: `language_mode` absent gives `en`; `hinglish` gives `hinglish`; `" Hinglish "` is trimmed and folded; `Hindi`, empty and `hinglish,en` warn once (`Invalid convo:config value for language_mode; using default`), give `en`, and echo none of the input. It appears in `overrides` only when valid. |
| L02 | The `convo config:` line matches `... greeting_tags=\S+ language_mode=(en|hinglish) read_ms=\d+ overrides=...` and still contains no URL or key. Exactly one such line per call. |
| L03 | **English is untouched.** With no hash, the STT settings passed to `STTCheckingDeepgramService` equal today's field for field (`language en-IN`, `endpointing 300`, same keys), the system prompt equals the stored v2 golden and the v21 text, and the seeded messages are identical. |
| L04 | Hinglish: STT `language` is `multi`; `endpointing`, `smart_format`, `interim_results` unchanged; `keyterm` present exactly when `stt_keyterms` is on; `base_url` EU exactly when `stt_region=eu`; `numerals` exactly when `stt_numerals` is on. |
| L05 | Prompt: `language_mode="en"` output has no `[LANGUAGE]` and no Devanagari; `hinglish` output ends with the addendum once, after the KB, for v2 and v21; the greeting message is the English greeting; the addendum is pinned by SHA-256 so any edit after your approval fails the test; its length is capped. |
| L06 | Addendum content: contains the feminine example and the Hindi fixed lines; contains no Latin-transliterated Hindi (the closed romanised list from the harness); every "Never ..." rule named in the Goal is present once. |
| L07 | Sentence splitting (the table above) through `SimpleTextAggregator`, in 1, 3 and random-size chunks: `।` and `?` after Devanagari release the sentence when the next non-space character arrives; an unpunctuated reply is released only by flush (the documented worst case); a mark with no following space is not released early. Guards a Pipecat upgrade. |
| L08 | `STTCheckingDeepgramService._on_message`: a result with `languages=["hi","en"]` pushes a `TranscriptionFrame` with `Language.HI`; with `["hi-Latn"]`, `["xx"]` or `["bho"]` it pushes the transcript with `language=None` and raises nothing; with no `languages` it is unchanged. |
| L09 | `stt check:` in hinglish mode: a Devanagari transcript gives `words>0` and `script=deva`; a Latin one `script=latin`; a mix `script=mixed`; `lang=` is the first code or `none`; no transcript text appears. An English-mode line is byte-identical to today's for the same transcript. |
| L10 | The `stt endpoint:` line states `language=en-IN` by default and `language=multi` in hinglish mode, and the `eu` mismatch WARNING still works. |
| L11 | Harness flags, each with a true and a false case: `masc_verb` (catches `बता सकता हूँ`, `कर रहा हूँ`, `करूँगा`, `समझ गया`; passes `बता सकती हूँ`, `कर रही हूँ`, `करूँगी`, `समझ गई` and the caller-side `मैं देख रहा हूँ` when it is in a caller line), `digits`, `wrong_script` (both directions), `english_to_hindi`, `hindi_to_english`, `no_final_punct`, `claimed_without_tool` with the three new English phrases (a true and a false case each, e.g. `set for Thursday` caught with no function call and passed with one, and `reset` not caught) and with the Hindi claims including `सेट कर दी`, `figure_not_in_kb` (a changed figure is caught, the KB's own `spoken` figure passes), `truncated`. |
| L12 | Harness `en` mode is unchanged apart from the three new `claimed_without_tool` phrases: the stored English summary and flag line are byte-identical. Devanagari `first_sentence_words` is the whitespace count. `parse_script` reads `hinglish_v21.txt` into 7 scenarios. |
| L13 | The wiring in `run_bot` with fakes (the `test_convo_config` G-tests' pattern): a hinglish hash gives an STT with `multi` and messages with the addendum; no hash gives today's, and the greeting queued is the English greeting in both. |
| L14 | The fixed sentences are unchanged: `commitments.*` and `CLOSING_PHRASE` equal their current strings in both modes (existing `test_tools` stays green). |

## Exit test (what I do by hand, with exact commands)

Tags: 🧑 YOU, 🤖 AGENT, 👀 VERIFY. No agent SSHes, merges, or handles a key. Run order matters: the two probes come first and may stop the task.

**Pre-flight (before merging).**

1. 🧑 **Deepgram probe, from your laptop, in the main checkout** (your key stays in your shell; record or pick a 3-to-5-second Hinglish clip, 8 kHz mono WAV, for example a line from the scripts above; put it in the scratch folder, not the repo):
   ```
   cd "/Users/vansh/Desktop/SALES AGENT/nxlyr-worktrees/021-multilingual"
   MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
   DEEPGRAM_API_KEY=... "$PY" scripts/probe_deepgram_multi.py ~/hinglish_8k.wav
   ```
   (`PY` is the AGENTS.md interpreter line; the key is typed by you, never passed to an agent.) It opens four streaming connections: host `global` and `eu`, each with key terms off and on, always `model=nova-3&language=multi&endpointing=300&smart_format=true`. For each it prints: connect result (open, HTTP status or close code), the first final transcript's script share (Devanagari / Latin), the `languages` codes returned, whether Pipecat's `Language()` accepts each code, time to first final result. 👀 **Stop and report if the EU row with key terms does not connect** (R2). The probe prints the transcript text on your screen; do not paste it anywhere with a phone number.
2. 🧑 **ElevenLabs probe** (your key in your shell):
   ```
   ELEVENLABS_API_KEY=... "$PY" scripts/probe_elevenlabs_hindi.py
   ```
   Eight fixed lines (Devanagari Hindi; Latin words inside Devanagari; "two point two crore rupees" inside Hindi; "Saturday को eleven बजे ठीक रहेगा।" and "the fifteenth of November" inside Hindi, which decision 9 makes the normal case; a pure English sentence; the AI-disclosure line), each requested from `eleven_v4_turbo` and `eleven_flash_v2_5`, voice `9lx2GDtpvyyNBM7O9Mmx` (the live voice from 2 Nov, on `eleven_v4_turbo`), both without `language_code` and with `"language_code": "hi"`, `pcm_8000`, saved as WAVs in the scratch folder with the status code and time to first byte. 👀 You listen: Devanagari natural? Latin words inside it natural? Does `hi` help or hurt? Record the verdict per line.
3. 🤖 Builder implements; 🤖 `/codex:review` is not used; Claude reviews the diff (different model). 🤖 Unit tests: the AGENTS.md command with `agent.test_language_mode` added, paste the tail.
4. 🧑 **Harness**, from `agent/` of the worktree (needs `OPENAI_API_KEY` in your `.env`, which the harness already loads; no agent reads it):
   ```
   cd agent
   "$PY" prompt_harness.py --prompt-version v21 --language-mode hinglish --script prompt_scripts/hinglish_v21.txt --runs 5 --out ~/021-harness-hinglish.txt
   "$PY" prompt_harness.py --prompt-version v21 --script prompt_scripts/conversation_v21.txt --runs 5 --out ~/021-harness-en.txt
   ```
   👀 Read the Hindi replies as text first. Pass: `masc_verb 0`, `digits 0`, `wrong_script 0`, `english_to_hindi 0`, `hindi_to_english 0` (scenario H4), `no_final_punct 0`, `truncated 0`, `figure_not_in_kb 0` (the Q1 check: every amount spoken matches a KB figure), `claimed_without_tool 0`; the English run's summary equals the stored `en` golden (the new English claim phrases may raise `claimed_without_tool` in a live run; a non-zero count there is a real finding, see the 27 Oct call). `p50_first_sentence_ms` for Hindi against English is reported, not a bar (the live bar is in step 9). If `truncated` is non-zero, the harness output proposes the hinglish `max_tokens` (smallest of 200, 220, 240 with `truncated 0` over the 5 runs).

**Live calls (after the merge deploys; the first call after a deploy is cold, so place and discard a warm-up call).**

5. 🧑 Set the switch (the whole `convo:config` stays as it is; **do not `DEL` the key**, which would also revert `prompt_version`, `stt_keyterms`, `stt_region` and `greeting_tags`):
   ```
   docker compose exec -T redis redis-cli HSET convo:config language_mode hinglish
   docker compose exec -T redis redis-cli HGETALL convo:config
   ```
   👀 Expect your five existing fields plus `language_mode hinglish`. Note `T0=$(date -u +%FT%TZ)`.
6. 🧑 Place the calls, each from the demo form as usual:
   - **Three English calls** in hinglish mode (you, in your usual English, 2 to 3 minutes each: price, payment plan, a booking for Saturday at eleven, goodbye). Pass (founder's bar): 3 of 3 answered only in English; **no drop in naturalness** against the control (score 1 to 10 as in 014; any lower score needs a stated reason); no stall of 2.5 s or more that the control does not have.
   - **Three Hinglish calls by you** (switch mid-sentence at least twice a call; one call speaks Hindi throughout; one with a booking and a correction, "Saturday, no, Sunday"; one with "क्या आप रोबोट हैं?"). Keep a **figure card**: for each answer on price, size, payment plan or possession write the figure you heard; it must equal the KB figure. Pass (founder's bar): **at least 2 of the 3 calls natural by your ear; 0 wrong figures, 0 masculine "I" verbs heard, 0 English replies to a Hindi-speaking caller, 0 invented facts**; the booking call leaves one live `call_commitments` row, one superseded row, and the Telegram alerts (the 008 invariants), with notes in English.
   - **Two or three calls by friends** with different accents (one Delhi Hindi, one Punjabi-inflected, one south Indian English if you can). They read a short list of things to ask, in their own mix. Pass (founder's bar): **at least 2 of 3 friends positive**; no crash, no silent call.
   - **Three control calls in English with `language_mode` unset** (`HDEL convo:config language_mode`), same script as the first group, for the latency comparison. Place them the same day, warm.
7. 🧑 Per call, one scoring row: understood (Y/N per turn), mix right (Y/N), figures right (Y/N), voice natural by ear (1 to 10), anything odd (a Hindi word read oddly, a Latin word mangled, a long pause).
8. 🧑 Evidence (copy `docker logs` output off the VPS only after checking for secrets; the log is scrubbed since 004, uvicorn's own lines are not):
   ```
   docker logs nxlyr_agent --since "$T0" 2>&1 | grep -E "convo config:|stt endpoint:|stt check:|Connection lost|stt fallback:|TOOL |prompt v2:" > ~/021-lines.txt
   ```
   👀 Expect per hinglish call: `convo config: ... language_mode=hinglish`, `stt endpoint: ... language=multi host=api.eu.deepgram.com` (or the host the probe chose), `stt check:` lines with `script=` and `lang=`. Per English-mode control call: `language_mode=en`, `language=en-IN`, no `script=`.
9. 🧑 **Latency** against English, with the tool you already use. Copy the latency files off the container first (they are lost on every deploy):
   ```
   python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" section6_real_call_events.log --from-call N --md
   ```
   `N` = the first call of the batch (instance numbers restart at 0 after a deploy). Report per group: STT first result, LLM first token, first-sentence wait, TTS TTFB, sum of stages p50 and p95, stalls. Founder's bar: hinglish-mode English calls have a **first-sentence wait p50 within +30 ms of the same-day English controls**. The other stages (STT first result, sum of stages) are reported for both groups with no bar; the Hinglish calls are reported with no bar (018's EU figure, about 275 ms for STT, is the older reference). Note the global-host fallback (Q4) adds about 85 ms to STT; if it is in use, say so next to the figure.
10. 🧑 Leak counts, on its own line, as in 015 and 014:
    ```
    "/Users/vansh/Desktop/SALES AGENT/tools/leak_counts.sh" "$T0"
    ```
    👀 Every count 0 except `masked`, which equals the number of calls. `grep -c "script=\|lang=" ~/021-lines.txt` is only to confirm the new fields exist.
11. 🧑 Switch off when done unless you decide to leave it on:
    ```
    docker compose exec -T redis redis-cli HDEL convo:config language_mode
    ```
12. 🤖 Memory: an inbox note for each vendor claim now verified or refuted; a PR section "Not verified" for anything not observed; an inbox note for the 27 Oct "set for Thursday" finding and the English-prompt follow-up. Claims in public copy: none.

## Risks and rollback

| # | Risk | Likelihood / impact | Mitigation |
| --- | --- | --- | --- |
| R1 | **Deepgram changed what `multi` is on 23 Oct 2026** (new 55-language model; a 10-language one is pinnable). Any figure I could find about Hindi on `multi` may describe the old model. | Medium / quality | Test on the model that serves today. Do not pin `version` unless the probe shows the new one is worse; Pipecat's ability to pass `version` is UNVERIFIED. |
| R2 | **`multi` plus key terms on the EU host is unverified.** A rejected parameter makes Pipecat retry the connection forever and the caller hears nothing. | Unknown / severe for the call | Probe step 1 before any call; hinglish mode is opt-in per call start, so a bad result costs nothing in production. Fallbacks in Design (drop key terms, or global host). |
| R3 | `Language()` cast raises on a code outside the enum and drops a transcript or restarts the connection. | Medium with `multi` / a lost turn | The `_on_message` guard and L08. In English mode the codes cannot trigger it. |
| R4 | **`en-IN` to `multi` may recognise Indian English worse**, and English callers are the live traffic. | Medium / regression | The three English calls in hinglish mode and the controls; default stays `en`, so the cost of a bad result is "leave it off". Optional later lever: Deepgram's new `language_hint` (not used here). |
| R5 | **Hindi costs more tokens**, so `LLM_MAX_TOKENS=160` may cut a reply mid-sentence with no final mark; the unpunctuated tail is then flushed at the end, or the reply is just cut. Not measured. | Medium / quality and latency | Harness flag `truncated` and `no_final_punct`. If either is non-zero, the fix is a larger `max_tokens` in hinglish mode, which is an LLM-block hunk outside the allowed `bot.py` regions (decision 5, approved). |
| R6 | v4 Turbo reads Devanagari or the Latin words inside it badly with the live voice. | Unknown / the product | Probe step 2 and the Hinglish calls. Fallback: `voice:config model eleven_flash_v2_5`. If both are poor, 021 does not ship `hinglish` as a demo mode and the finding goes to the founder. |
| R7 | Smart Turn v3 is tuned for specific languages; Hindi support is UNVERIFIED in the installed code. A long Hindi pause may be cut early or wait the 0.8 s backstop. | Medium / feel | Founder's ear on turn-taking in the Hinglish and friend calls; the 011 backstop stays. Any change is a turn-release task, not this one. |
| R8 | The model changes a figure (lakh and crore, or an irregular Hindi number). | Medium / **trust** | Number safety: copy the `spoken` phrase; the `figure_not_in_kb` flag; the figure card on every call. 0 wrong figures is a hard bar. |
| R9 | The model breaks a 008 rule in Hindi ("बुक कर दी" without calling the tool). | Medium / trust | The addendum's last line, the Hindi claim patterns in `claimed_without_tool`, and the booking call's row-and-alert check. The English side of the same hole ("set for Thursday" before the tool returns, seen live on 27 Oct) is only detected here, not fixed: a follow-up task. |
| R10 | The addendum's Devanagari has an error. | Low now / quality | The founder checked every phrase on 2 Nov and corrected five items (decision 11). The text is pinned by a hash in a test, so any later edit needs a fresh check. |
| R11 | A fixed failure sentence is heard in English by a Hindi caller. | Low frequency / experience | Accepted and stated (decision 2). |
| R12 | `bot.py` merge conflict with 022. | Medium / time | Hunks stay in separate regions (STT block 469-495, prompt build 530-563). Whichever merges second rebases. |

**Rollback, fastest first (no deploy):** `HDEL convo:config language_mode` returns every new call to English and today's STT. A call in flight keeps its mode until it ends. `HSET voice:config model eleven_flash_v2_5` swaps the voice. **Code rollback:** revert the merge commit; since `en` is the default and the code changes are additive (one optional argument, one guard, appended log fields), reverting loses only the hinglish mode. No data to undo (nothing is written). Merge = redeploy, so a revert is a redeploy too; the first call after it is cold.

## Open questions for me

### Decisions (founder, 2 Nov 2026)

1. **Amounts (Q1): English number words in Latin letters, copied from the KB `spoken` line** ("two point two crore"), even inside Hindi. No Hindi number table. The harness flag `figure_not_in_kb` is the required check: every amount spoken in a reply must match a KB figure (pass: 0).
2. **Fixed 008 sentences and the goodbye (Q2): stay English for now.** The PR must say so in a short "Known limits" line. No Hindi twins in this task.
3. **Endpointing (Q3): stays 300.** Changing turn timing is out of scope.
4. **EU host (Q4):** if the probe shows `multi` is not served on `api.eu.deepgram.com`, hinglish calls use the global host (about 85 ms slower, accepted). If key terms are rejected with `multi`, they are dropped in hinglish mode only; English mode keeps them. Exit step 1 decides both.
5. **`max_tokens` (Q5): yes**, in hinglish mode only, English unchanged. The number is proposed from the harness `truncated` flag (smallest of 200, 220, 240 with `truncated 0`). This is the one `bot.py` hunk allowed in the LLM block (497-504), and it is added to Files in scope. Only if `truncated` is non-zero.
6. **Pass bars (Q7), replacing the proposals above:** English calls in hinglish mode show no drop in naturalness and a first-sentence p50 within +30 ms of English mode; at least 2 of the founder's 3 Hinglish calls natural; at least 2 of 3 friends positive; zero masculine first-person verbs; zero English replies to a Hindi-speaking caller; `claimed_without_tool` 0; leak counts 0 (and, from before, 0 wrong figures, 0 failed writes).
7. **Control calls (Q8):** three same-day English controls stay in (the +30 ms bar needs them).
8. **Overlap with 022:** 022 also adds a `convo:config` field. Whichever merges second rebases `convo_config.py` (`_ALLOWED`, `_DEFAULT_RAW`, `ConvoConfig`, `parse`, `log_line`); `log_line` field order is decided at that rebase, and the tests that pin the line are updated by whoever rebases.
9. **Numbers, days, months, dates and times in English words (founder, 2 Nov).** Every number, count, day name, month name, date and time is said in English words in Latin letters; Hindi is only the connecting words. Confirmed: **"eleven बजे"** with बजे in Devanagari (also "eleven in the morning"); **relative days always become "today", "tomorrow", "day after tomorrow"**; **"एक" meaning "a" is fine**. The old line that gave Hindi words for days and times is gone, and the addendum's examples contain no Hindi day, month, time or number word. Harness: new flags `hindi_calendar` and `hindi_number`, scripts H1/H7 reworded, new H8.
10. **Script (A): Devanagari for Hindi words**, from your voice test (v4 Turbo with Devanagari was clearly best). Voice for the probe: `9lx2GDtpvyyNBM7O9Mmx`. Fix found while editing: the AI line wrote "असिस्टेंट", an English word in Devanagari, which broke the addendum's own rule; it is now "AI assistant" in Latin letters.
11. **Devanagari check (B), done by the founder on 2 Nov; everything else is correct.** Applied exactly: (a) "जी, मैं सुन सकती हूँ।" is now "जी, आपकी आवाज़ आ रही है।"; (b) "माफ़ कीजिए, मैंने ठीक से सुना नहीं।" is now "माफ़ कीजिए, मुझे ठीक से सुनाई नहीं दिया।"; (c) the AI line is now "जी, मैं एक AI assistant हूँ, Next Layer की तरफ़ से call कर रही हूँ।"; (d) caller script H1 "…लोकेशन पक्का जाननी है" is now "…लोकेशन पक्के तौर पर जाननी है"; (e) the Numbers line's examples no longer contain a Hindi day, time or number word. **Harness:** `claimed_without_tool` gains `set for`, `fixed for`, `scheduled for` and `सेट कर दी`, in both modes. **English prompt text: not changed in this task**; the English rule is a follow-up (Non-goals, R9).

**Nothing is open.** The founder starts the build in Codex personally.
