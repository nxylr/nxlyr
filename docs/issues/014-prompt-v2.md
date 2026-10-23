# 014 — Prompt v2: sound like a person, stop ending calls after a booking

**Status: r3 APPROVED by the founder; r8 aligns the booking-result `next_step` and its P8 test with the built code ("do not hang up; let the caller lead"), and adds the founder's `objections.price` wording from r7 ("What range were you thinking of?") to one combined guarded `UPDATE` with one rollback for both original texts. Nothing committed.**
Worktree `../nxlyr-worktrees/014-prompt-v2`, branch `task/014-prompt-v2`, from `origin/main` at `0fe6005`.

## Goal

Make the bot sound like a natural human caller rather than a script, without getting slower, measured against the founder's by-ear notes in `docs/baselines/2026-10-22-baseline.md` ("What the caller heard") and `docs/baselines/2026-10-23-011-exit.md` ("By ear").

It covers the founder's findings:

1. The opening names neither Aarya nor the company, only "the enquiry you sent in", and for a demo call it is untrue: the visitor asked for a demo, not about a property.
2. A second greeting when the caller says hello.
3. Filler openers ("Great", "I see", "Sure thing", "Absolutely", "Sure", "I hear you", "Fair question", "I appreciate you sharing"), and echoing one-word answers.
4. Lists every fact, then a question; almost every line ends in one.
5. Repeats the project's full name every turn.
6. Long, preachy sentences; repeated facts.
7. Says money and splits badly ("Rs 12 thousand", "25-25-25-25").
8. Once called the caller "Daniel".
9. Repeats a misheard project name ("Eridian Heights") instead of confirming it.
10. BUG: the bot sometimes ends the call after `book_site_visit`.
11. Whether the sample exchanges in `agent/bot.py` reach the model.

Founder decisions of 2026-10-23 that this spec carries out (see `docs/memory/decisions.md`):

- The bot says it is an AI only when asked, then at once and truthfully, never denying or dodging. This is one clearly marked rule, switchable to up-front disclosure if the lawyer says so.
- The agent is Aarya, female voice. English verbs have no gender, so the prompt says only "You are Aarya, a woman"; Hindi forms come back with the Hinglish task. The company is named in speech as "Next Layer" (`COMPANY_SPOKEN`) and shown as "NXLYR" in logs, UI and docs (`COMPANY_DISPLAY`); the prompt and every spoken string use only the spoken form.
- Two greeting templates chosen by lead source: `demo_form` and `lead`. The greeting is seeded into the context, so it exists once.
- No caller-name source exists until task 012. Until then the bot never uses a name, "sir" or "ma'am".
- The prompt has three blocks (core rules, real-estate pack, company values) with no config system.
- Knowledge-base wording changes are SQL for the founder to review and run. Nothing here executes SQL.

## Non-goals

- Tool semantics: no commitments rows, no truthful-result rework, no notification. That is 008. This task changes only the tools' description strings, one tool-result hint and the closing phrase.
- Caller-name plumbing, form of address (012).
- Plumbing a lead source from `server.py` into `run_bot()`. `server.py` is untouched, so only the demo template can be reached on a real call today (Change 2).
- Call record and transcripts (006, 007).
- Start-up time, greeting latency, the cold first call and the 6 s silent-caller greeting (L1). I add no start-up timing logs.
- STT (Deepgram key terms, amount mishearing), TTS voice or model, turn-taking, VAD, `LLM_MAX_TOKENS` / model / temperature.
- The second LLM call after a tool (about 640 ms). I do not remove it. A shorter spoken reply after a tool helps a little; it does not fix this.
- Hindi or Hinglish in the prompt. The bot is English-only today (STT is `en-IN`), and Hindi words in the prompt can prime Hinglish answers the voice may mispronounce.
- A per-industry config system, a second tenant, loading company values from the database.
- Any change to the dashboard, `server.py`, `kb_loader.py`, nginx or CI.
- Adding `test_prompt` to the AGENTS.md command list (goes in the close-out memory PR).

## What I read, and what I did not

Read in this worktree (`0fe6005`):

| Where | What I checked |
| --- | --- |
| `agent/bot.py:301-326` | `DEFAULT_PERSONA_CONTEXT`, `FEW_SHOT_EXAMPLES` |
| `agent/bot.py:329-481` | `build_system_prompt()` in full: role 352-363, rules 379-404, persona 408-418, examples 420, tools 433-458, date 467-471, assembly 473-481 |
| `agent/bot.py:489-492` | `GREETING` |
| `agent/bot.py:495-718` | `run_bot()`: prompt built at 615-623 with only `project_kb=` (so `agent_name` and `lead_name` are never passed), `on_client_connected` 678-693 |
| `agent/tools.py:65-76` | `CLOSING_PHRASE` |
| `agent/tools.py:204-274` | `book_site_visit()` and its schema |
| `agent/tools.py:286-343` | `transfer_to_human()` and its schema |
| `agent/tools.py:350-454` | `END_CALL_OUTCOMES`, `end_call()`, `END_CALL_SCHEMA` |
| `agent/kb_loader.py:19-93` | `load_kb()` / `_fetch_kb()`: the KB is `projects.config` returned as one dict |
| `agent/prompt_harness.py:43-57, 158-228` | imports `GREETING` and `build_system_prompt` from `bot`; seeds `[system, assistant GREETING]` |
| `agent/server.py:131-138` | `DemoCallRequest` has `phone_number` and `consent_text_version` only: no name field exists |
| `agent/Dockerfile:65`, `agent/.dockerignore:56-57` | `COPY *.py ./` ships any new `agent/*.py`; `prompt_harness.py` is excluded from the image |
| Pipecat 1.5.0 in the main checkout's venv: `frames/frames.py:790-804`, `processors/aggregators/llm_response_universal.py:1641-1643, 2055-2077, 1927-1928` | `TTSSpeakFrame.append_to_context`, what an interruption does to the assistant turn |
| `agent/server.py:690-760`, `agent/ws_auth.py:20-24` | `/ws` handler: `run_bot(replay_websocket)` is called with no information about the lead; the binding key is `ws_bind:<call_sid>` and carries no source |
| Whole-worktree greps | `persona` (only `bot.py` and one planned-feature line in `product.md`); `end_call_tool_invoked`, `stop_when_done`, `worker.cancel` (only `tools.py` and `bot.py:698`) |
| Whole-worktree grep for `payment_plan`, `tranches`, plan `name` reads; `/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py` (flags, instance numbering) | No code reads `payment_plan`; instance #0 is the first call after a container start and `--from-call N` drops lower instances |
| `docs/baselines/*`, `docs/memory/hot.md`, `decisions.md`, `product.md`, `mistakes.md`, `patterns.md`, inbox note `2026-10-23-bot-may-end-call-after-book-site-visit.md` | Founder notes, decisions, truth rules |
| `agent/prompt_harness_transcripts/06_tool_site_visit.txt`, `07_tool_natural_close.txt` | Old (2026-08-08) harness runs; show the style, not the current prompt |

Ran: `build_system_prompt()` with an empty KB in the main venv, to count what the current prompt contains (below), and `agent.test_turn_release` (13 tests pass in this worktree).

**UNVERIFIED** (not checked, or checked only by reading):

- The tool-call order on the one call that ended after booking, and therefore whether `end_call` came in the same assistant message as the booking or in the following turn (the spec states both and covers both). I have not seen the log lines or the Redis output. The "1 of 10 calls, `site_visit_booked=true`, `end_call_tool_invoked=true`, no transfer" figure is from the brief; the inbox note has only the counts (10 booked, 9 transfers, in both batches).
- The mechanism of the second greeting (two candidates below). The two founder notes disagree: the baseline says it happens "whenever the caller greets"; the 011 exit note says that when the caller speaks first there was no second greeting.
- The real knowledge base beyond what you pasted. You ran the read-only queries yourself (see "Data touched"): `projects.tenant_id` exists, `config` is jsonb, the only payment key is `payment_plan`. You pasted `payment_plan` and the `objections` object; I have seen no other KB text.
- That the async tool behaviour described in the `tools.py:200-203` comment ("the LLM continues the conversation immediately") holds in Pipecat 1.5.0. I did not re-read `llm_service.py`.
- The SQL in "Data touched": there is no Postgres here, so the `UPDATE` and its rollback are untested even locally.
- The latency bases (LLM first token p50 651 ms, first-sentence wait p50 76 ms) come from the 23 Oct exit-test report you ran. They are not in `docs/baselines/2026-10-23-011-exit.md`; they can be recomputed from your saved events.log with `latency_report.py`.

## Findings from the code (before the design)

**F-a. The sample exchanges do reach the prompt, and they teach the style.** `bot.py:420` joins `FEW_SHOT_EXAMPLES` into `examples_block`; `bot.py:479` places it in `[CONVERSATION EXAMPLES]`. I assembled the current prompt and counted the founder's phrases in it (whole word, case-sensitive): "Fair question" 1 (example 3, `bot.py:322`), "I hear you" 2 (`bot.py:384, 387`), "Sure" 2 (`bot.py:317, 380`), "Got it" 1 (`bot.py:380`), "Right" 3 (`bot.py:380, 384, 387`). The rules even instruct it: `bot.py:380` says `Use "Right", "Sure", "Got it" as acknowledgements.` The example at `bot.py:316-318` also promises "I'll have that sent right after this call", which the product cannot do (`product.md`: brochure/WhatsApp is planned, not built). The current static prompt is 4,662 characters (797 words) with an empty KB.

**F-b. The bot never learns its own name.** `bot.py:619` calls `build_system_prompt(project_kb=project_kb)`, so the role line renders as `You are the assistant, a pre-sales representative at the developer. You are calling the caller who filled in an enquiry form about the project.` (confirmed by running it with an empty KB). Aarya does not exist in the prompt, the greeting names nobody, and with no name given the model filled the gap itself ("Daniel").

**F-c. `bot.py:390` says `Never reveal you are an AI.`** That contradicts the founder's decision and must go.

**F-d. The rules force the question at the end and the sermon.** `bot.py:403` `Always end with a clear next step.` produces a question on almost every line. `bot.py:391` `If asked about pricing, first build value, then state range.` produces the build-up. `bot.py:381` allows up to three sentences per response, and `LLM_MAX_TOKENS=160` (`bot.py:272`) allows far more than one point.

**F-e. The comment at `bot.py:197-199` is wrong for the installed Pipecat 1.5.0.** It says an interrupted reply "is discarded rather than committed to the context". In `llm_response_universal.py:1641-1643`, `_handle_interruptions` calls `_trigger_assistant_turn_stopped(interrupted=True)`, which calls `push_aggregation()` (`:2055-2059`) *before* `reset()`. So whatever words of the greeting had been spoken when the caller cut in are committed as an assistant message; if none had been spoken yet, nothing is. Either way the context may hold a partial or empty greeting. That is one plausible way the model comes to greet again (candidate H1). Candidate H2: the greeting plays in full and is committed, and the model re-greets anyway because the prompt never says the greeting happened (the role line at `bot.py:352-363` is silent about it). Neither is proven on a call (UNVERIFIED).

## Design (files to touch and why)

### Files in scope

| File | Change | Why |
| --- | --- | --- |
| `agent/prompt.py` (new) | Pure Python, no Pipecat import. Company-values constants, `build_greeting()`, `build_system_prompt()`, `build_initial_messages()` and the three blocks. | Moves the prompt out of `bot.py` (hot.md Next 1 asks for this). It keeps this diff away from the L1 hunk in `run_bot()` and makes the prompt testable without importing Pipecat or the logging setup. |
| `agent/bot.py` | Delete `DEFAULT_PERSONA_CONTEXT`, `FEW_SHOT_EXAMPLES`, `build_system_prompt()`, `GREETING` (about 200 lines, `bot.py:295-492`). `run_bot()` builds the messages with `LEAD_SOURCE_DEMO_FORM` (no new parameters), seeds the greeting into the context, pushes it with `append_to_context=False`, and logs one line. Fix the wrong comment at 197-199. | Greeting and second greeting (Change 5). |
| `agent/tools.py` | Description strings for `book_site_visit` and `end_call`; a `description` on the `outcome` property; a `next_step` hint in the `book_site_visit` result; `CLOSING_PHRASE` imported from `prompt`. Nothing else. | The end-call bug. |
| `agent/prompt_harness.py` | Replace the `GREETING` and `build_system_prompt` imports with `build_initial_messages(project_kb)` and use its result as the starting history. | `GREETING` no longer exists, and the harness should start from exactly the messages production starts from. |
| `agent/test_prompt.py` (new) | The automated tests below. | |
| `docs/issues/014-prompt-v2.md` | This spec. | |

Not touched: `server.py` (so `/ws` still cannot pass a lead source; see Change 2), `kb_loader.py`, `demo_guard.py`, `ws_auth.py`, `log_scrub.py`, `week2_latency_observer.py`, `dashboard/`, `infra/`, `.github/`, `supabase/`, and any `.env*`.

Builder: Codex. Reviewer (must differ): Claude, on the diff, with the unit tests re-run.

### Change 1: three blocks and company values in `agent/prompt.py`

The block names are `[CORE RULES]` (any industry), `[REAL ESTATE PACK]`, `[COMPANY]`. After them come the data sections `[CURRENT DATE]`, `[PROJECT KNOWLEDGE BASE]` and `[HOW IT SOUNDS]` (the sample exchanges, last because the model weights recent text most).

Company values are plain module constants, not a config system:

```python
AGENT_NAME = "Aarya"
COMPANY_DISPLAY = "NXLYR"        # logs, UI, docs. Never spoken, never in the prompt.
COMPANY_SPOKEN = "Next Layer"    # every spoken string and the whole prompt (founder, 2026-10-23)
AI_DISCLOSURE_MODE = "on_ask"    # "on_ask" | "upfront"; the one switch for the lawyer's answer
LEAD_SOURCE_DEMO_FORM = "demo_form"
LEAD_SOURCE_LEAD = "lead"
CLOSING_PHRASE = "Thanks for your time. Have a good day."
BANNED_OPENERS = (
    "Great", "I see", "Sure thing", "Absolutely", "Sure", "I hear you",
    "Fair question", "I appreciate you sharing", "Got it", "Right",
)
```

The prompt never contains the letters "NXLYR", because the voice may spell them out. The only place `COMPANY_DISPLAY` is used by the call path is the start-up log line.

**Removed with no replacement, and the proof that nothing else uses it.**

| Removed | Evidence it is unused elsewhere (grep of the whole worktree, excluding `.git`, `venv`, `node_modules`) |
| --- | --- |
| `[PERSONA CONTEXT]` block, `DEFAULT_PERSONA_CONTEXT`, the `persona_context` parameter | Every hit is in `agent/bot.py`: the definition (`:301-305`), the parameter and its use (`:336, 347-350`), the block text (`:408-418`) and its slot in the prompt (`:478`). No test, no `prompt_harness.py` (it calls `build_system_prompt(project_kb=...)` only, `:203`), no server, dashboard or script reads or sets it. The one other mention is `docs/memory/product.md:19`, where "persona classification" is listed as planned. |
| `[ROLE]`, `lead_name`, `agent_name`, `developer_name` parameters | `bot.py:619` is the only production caller and passes none of them (that is finding F-b); `prompt_harness.py:203` passes none. |
| `[CONVERSATION EXAMPLES]`, `[TOOLS]` as they are | Replaced by `[HOW IT SOUNDS]` and by rules inside core and pack. |

The block's text is dead scaffolding ("Fields still to capture: (none tracked yet)", "Reclassification trigger: False") plus a confirming question the model might say aloud. When Week 5 builds persona scoring it adds its own block.

### Change 2: greeting, two templates chosen by lead source (current and proposed)

Current, `agent/bot.py:489-492`:

```python
GREETING = (
    "Hi, thanks for your interest — I'm calling about the enquiry you sent in. "
    "Have you got a couple of minutes to chat?"
)
```

That is untrue for a demo call: the visitor asked for a demo, not about a property. Proposed, in `prompt.py`:

```python
def build_greeting(lead_source: str, project_name: str | None = None) -> str:
    who = "Aarya, an AI assistant" if AI_DISCLOSURE_MODE == "upfront" else "Aarya"
    opening = f"Hi, this is {who} from {COMPANY_SPOKEN}."
    if lead_source == LEAD_SOURCE_DEMO_FORM:
        sample = f"using a sample project, {project_name}" if project_name else "using a sample project"
        return (f"{opening} You asked for a demo call, so I'll walk you through "
                f"how I'd speak to a buyer, {sample}. Is now a good time?")
    if lead_source == LEAD_SOURCE_LEAD:
        about = f"You enquired about {project_name}." if project_name else "I'm calling about the enquiry you sent in."
        return f"{opening} {about} Is now a good time?"
    raise ValueError(f"unknown lead_source {lead_source!r}")
```

What each speaks with `AI_DISCLOSURE_MODE = "on_ask"`:

| Lead source | `project_name` is | Spoken |
| --- | --- | --- |
| `demo_form` | the KB's `project_name` (the sample project) | "Hi, this is Aarya from Next Layer. You asked for a demo call, so I'll walk you through how I'd speak to a buyer, using a sample project, Meridian Heights. Is now a good time?" |
| `lead` | the project in the lead record | "Hi, this is Aarya from Next Layer. You enquired about Meridian Heights. Is now a good time?" |
| `lead` | nothing (lead record names no project) | "Hi, this is Aarya from Next Layer. I'm calling about the enquiry you sent in. Is now a good time?" |

In `lead` mode the project name comes only from the lead record, never from the KB, so a project is named only when the lead enquired about it. With `"upfront"` the first sentence becomes "Hi, this is Aarya, an AI assistant from Next Layer." Both templates open with the same seven-word first sentence, which is the only one the caller waits for.

**Which source a call gets today.** `server.py:744` calls `run_bot(replay_websocket)` with nothing about the lead, `/ws` has no field for it, and `DemoCallRequest` carries only a phone number and a consent version. Every call today comes from `/demo/call` (or the unauthenticated `/start`, refused under enforce). So `run_bot()` takes **no** `lead_source` parameter and always builds the `demo_form` messages: the `lead` template is **built and unit-tested but unreachable on a real call by construction** until task 012 adds the plumbing (and the parameter) in `server.py` and `run_bot()`. Test P18 checks the signature. `/start` calls, if any, get the demo greeting.

### Change 3: closing phrase (current and proposed)

Current, `agent/tools.py:76`:

```python
CLOSING_PHRASE = "Thanks for your time — that's everything I needed. Have a good day."
```

"That's everything I needed" is call-centre wording, and it is spoken right after a confirmation when the bug fires. Proposed (defined in `prompt.py`, imported by `tools.py`): `"Thanks for your time. Have a good day."` It names no company, promises nothing and mentions no time, and stays true after `not_interested` and `wrong_number` (the requirement in the comment at `tools.py:65-75`).

### Change 4: the style rules (current and proposed)

Current, `agent/bot.py:379-404`, as the model sees it (`[RULES]`):

```text
- Speak naturally. Use "Right", "Sure", "Got it" as acknowledgements.
- Keep each response under 3 sentences. This is a phone call.
  Too long: "Right, I hear you. While some projects might promise quicker possession, our timelines ensure the highest quality construction and attention to detail. Plus, the amenities and location really make the wait worthwhile. Would you be interested in visiting the site?" (4 sentences — reassures three times before making the offer.)
  Correct: "Right, I hear you — the wait buys you quality construction. Want to see the site for yourself?" (2 sentences, same offer, said once.)
- Never read out a list. Speak in natural flowing sentences.
- Never reveal you are an AI.
- If asked about pricing, first build value, then state range.
- Never give discounts or make promises not in the project config.
- Never claim a reputation, track record, or quality standard (e.g. "strong track record", "highest quality", "excellent reputation") unless it is a specific fact from the project knowledge base. If you don't have one, redirect to something concrete you do have, or defer — the same way you already defer on prices and dates.
- Never promise when a follow-up will happen. "shortly", "soon", "right away", "within the hour", "today" — no such commitment exists to make. A colleague following up is true; a colleague following up *soon* is not. This holds on every turn, including when the caller pushes back a second time and you are restating something you already said.
- Always end with a clear next step.
```

Current sample exchanges, `agent/bot.py:309-326` (they reach the prompt, finding F-a):

```text
Buyer: What's the price for a 3 BHK?
You: Depends a bit on the tower and floor, but I can get you exact numbers — are you looking at this for yourself, or as an investment?

Buyer: Can you send me a brochure?
You: Sure, I'll have that sent right after this call. While I have you — what's prompting the search, a new home or just exploring for now?

Buyer: This sounds expensive.
You: Fair question. The payment plan alone is pretty flexible, and once you see everything laid out it tends to make a lot more sense. Want me to send over the full breakdown?
```


Proposed prompt for the `demo_form` source, in full. `{project_name}` is the KB's `project_name` (fallback "the sample project"); the date line and the KB JSON are rendered at call time. The greeting is **not** quoted in the system prompt: it is the first assistant message (Change 5), so it exists once. Measured by the builder with an empty KB: **4,790 characters, against 4,662 today** (about 30 more tokens, 3%; my own draft measured 4,804 with Meridian Heights substituted, the gap being a shorter placeholder and the "the sample project" fallback; the KB JSON is the bulk of the real prompt and is unchanged). Test P12 caps it. `[COMPANY]` has no Hindi: English verbs have no gender, so "a woman" is enough, and Hindi words can prime Hinglish answers.

```text
[CORE RULES]
This is a live phone call. Everything you write is spoken aloud.
- Say one or two short sentences, about twenty-five words. Make one point, then stop and let the caller lead. Never recite everything you know.
- Start with the answer itself, not a reaction. Never open a reply with: Great, I see, Sure thing, Absolutely, Sure, I hear you, Fair question, I appreciate you sharing, Got it, Right.
- End with a question only when the answer moves the conversation forward. Most replies end with a statement.
- Do not echo a one-word answer such as "yes" or "okay". Carry on with the next useful thing.
- Say each fact once. No lists. No lecturing, long reassurance, or praise for the caller's questions.
- Write for the ear. Amounts, percentages, dates and times are words: "one point two crore rupees", "twenty-five percent", "Saturday the fifteenth", "eleven in the morning". Never digits, "Rs", a rupee sign, "Cr", or a dash between numbers. Function arguments are the one exception.
- You do not know the caller's name. Never use a name for the caller, and never say "sir" or "ma'am", even if they tell you their name.
- If you are not sure you heard a name or a number, check it as a question first. Never repeat a name you are unsure of.
- Use only facts in the knowledge base; if you lack one, say so in one sentence. Never invent a price, date, distance, name, reputation or track record. No discounts.
- Never say when anything will happen: no "shortly", "soon", "right away", "today".
- You have three real functions. Call one only when its condition is met, in the same turn you speak about it. Never say something is done unless you called the function that does it.
- end_call hangs up on the caller. Call it only when the caller's latest message says goodbye, says they are finished, asks to end the call or stop calling, or says it is a wrong number. A booking, a passed-on question or a finished answer is not the end. Never call end_call in the same turn as another function, or in the turn after a function result unless the caller's latest message already said goodbye. If unsure, stay on the line.
- transfer_to_human only logs a request. It connects nobody and schedules nothing: say a colleague will follow up, with no time.

[REAL ESTATE PACK]
- Say the project's full name once. If the greeting already said it, say "the project" or "it" from then on, unless asked.
- If the caller says a project name close to {project_name} but not the same, ask "Did you mean {project_name}?" before answering.
- Answer what was asked with one or two facts.
- Price: give the figure asked for, in words, once, with no build-up. If the caller says it is expensive, ask what range they had in mind. Do not defend the price.
- Say a payment plan as one plain sentence, using the knowledge base's "spoken" line if there is one. Never read it out as a ratio; say it as a sentence.
- Suggest a site visit once, after the caller shows interest. If they agree, ask which day and time suit them, then call book_site_visit as soon as they give one; preferred_date is a real future date worked out from [CURRENT DATE]. After booking, confirm the day and time in one sentence and let the caller lead. The call carries on.

[COMPANY]
You are Aarya, a woman, and you work for Next Layer.
This is a demo call. The caller asked for a demo of how you would speak to a buyer, using a sample project, {project_name}. Treat them as that buyer. If they ask what this is, say it is a demo.
Your greeting has already been spoken: it is the first assistant message. Never greet or introduce yourself again. If the caller only says hello, answer in five words or fewer and wait. Only if they ask who you are or why you called, say your name, Next Layer and the reason, once. If they ask which company, say Next Layer.
You cannot send brochures, WhatsApp messages, emails or links, and you never offer to.
AI DISCLOSURE (switch: AI_DISCLOSURE_MODE in prompt.py): Do not mention that you are an AI unless asked. If the caller asks whether you are an AI, a bot, a machine, a recording or a real person, answer at once and truthfully: "I'm an AI assistant calling for Next Layer." Then carry on. Never deny it, never dodge, never claim to be human.

[CURRENT DATE]
Today is {weekday}, {day} {month} {year} ({iso date}).
Work out every date the caller mentions relative to this, and never emit a date earlier than it.

[PROJECT KNOWLEDGE BASE]
{json of projects.config, unchanged}

[HOW IT SOUNDS]
Caller: Yes, go ahead.
You: So, is this for your own family, or as an investment?

Caller: This sounds expensive.
You: What range were you thinking of?

Caller: Hello?
You: Yes, I can hear you.

Caller: Saturday at eleven works for me.
You: I've put you down for Saturday at eleven in the morning.
```

For the `lead` source only two things change: the demo paragraph in `[COMPANY]` becomes `The caller sent us an enquiry about {lead_project_name}. Treat them as a buyer who enquired.` (or `The caller sent us an enquiry. Treat them as a buyer who enquired.` when the lead record names no project), and `{project_name}` in the pack becomes `{lead_project_name}` (or the KB's `project_name` when the lead record names none).

Notes on the text:

- Where it came from: the old rules about discounts, reputation, follow-up timing, the transfer lie and the date handling are kept in shorter form (they came from earlier rating and harness findings; see the comments at `bot.py:365-378` and `tools.py:310-316`). The "Too long / Correct" pair is dropped because its "Correct" half contains "Right, I hear you" and a question.
- The banned-opener line is the only place the banned phrases appear in the prompt. Listing them risks priming, so the exit test watches for substitutes ("Okay", "Of course", "Alright", "Understood") and the list lives in one tuple that is easy to extend.
- The booking example says "I've put you down", not "booked": the tools only set Redis flags today (`product.md`), so a truthful wording is 008's job and I do not make it worse here.
- No promise to send, confirmed. I scanned the assembled prompt (outside the KB JSON) for brochure, WhatsApp, email, link, send and sent: the only hit is the `[COMPANY]` sentence "You cannot send brochures, WhatsApp messages, emails or links, and you never offer to." None of the 4 sample exchanges, the greetings or the closing phrase contains such a word. Test P3 checks the samples and P19 checks the rest of the prompt. This is the prompt half of audit finding F05 (`sw_docs/NXLYR-independent-audit.md:65`: the few-shot brochure promise and the KB's WhatsApp "right away"); the KB half is the second `UPDATE` in "Data touched", because the model reads the KB as fact.
- Which company: the `[COMPANY]` block says "If they ask which company, say Next Layer", and every spoken string uses the spoken form.
- Three of the four sample replies end in a question, on purpose: those are the places a question moves the conversation.

**The AI-disclosure rule** is the `AI DISCLOSURE` paragraph at the end of `[COMPANY]` plus the greeting. Switching to up-front disclosure is one edit, `AI_DISCLOSURE_MODE = "upfront"`: the greeting gains "an AI assistant" and the paragraph is replaced by:

```text
You told the caller in your greeting that you are an AI assistant. If they ask again, confirm in a few words. Never deny it and never claim to be human.
```

### Change 5: seed the greeting into the context (second greeting)

Two candidate causes of the second greeting, both UNVERIFIED on a real call (finding F-e): a partial or empty greeting committed after an interruption (H1), or a full greeting plus a prompt that never says it happened (H2). The design covers both:

1. Prompt: `[COMPANY]` says the greeting has already been spoken, never to greet again, and what to say to a bare "hello" (five words or fewer) and to a real "who is this?" (name, company and reason, once).
2. Context: the full greeting is the first assistant message, and the speech frame does not append it a second time. In `prompt.py`:

```python
def build_initial_messages(project_kb, *, lead_source=LEAD_SOURCE_DEMO_FORM,
                           lead_project_name=None, today=None) -> list[dict]:
    project = project_kb.get("project_name") if lead_source == LEAD_SOURCE_DEMO_FORM else lead_project_name
    return [
        {"role": "system", "content": build_system_prompt(
            project_kb=project_kb, lead_source=lead_source,
            lead_project_name=lead_project_name, today=today)},
        {"role": "assistant", "content": build_greeting(lead_source, project)},
    ]
```

In `bot.py`, `run_bot()` (current lines 615-623 and 693):

```python
messages = build_initial_messages(project_kb, lead_source=LEAD_SOURCE_DEMO_FORM)
greeting = messages[-1]["content"]
logger.info(
    f"prompt v2: chars={len(messages[0]['content'])} lead_source={LEAD_SOURCE_DEMO_FORM} "
    f"disclosure_mode={AI_DISCLOSURE_MODE} company={COMPANY_DISPLAY}"
)
context = LLMContext(messages=messages, tools=TOOL_SCHEMAS)
...
await worker.queue_frames([TTSSpeakFrame(greeting, append_to_context=False)])
```

This makes the context identical whether the caller talks over the greeting or not, and it matches what `prompt_harness.py` already did. The log line carries no prompt text and no names, so the 004 leak gates still read 0. Cost: if a caller's "hello" cancels the greeting before any word is heard, the model believes it introduced itself when the caller heard nothing; the "who is this" rule is there for that case. Tests P13 and P18 check that the greeting appears once.

### Change 6: spoken amounts and the payment plan

The core rule "Write for the ear" covers amounts, percentages, dates and times; the pack says to give the payment plan as one plain sentence, using the KB's `spoken` line. The KB side is one `UPDATE` (Data touched): `payment_plan.name` loses its "25:25:25:25" and gains a `spoken` key, with `tranches` untouched, so the model has a sentence to say instead of a ratio to read. The rule does not apply to function arguments (`preferred_date` stays `YYYY-MM-DD`). Not fixed here: amounts misheard by STT (4 of 10 baseline calls, inbox `2026-10-22-baseline-amounts-misheard-on-4-of-10-calls.md`); the "check a name or number you are unsure of" rule helps the symptom, the cause is the STT A/B task.

### Change 7: misheard project name

Pack rule: if the heard name is close to `{project_name}` but not the same, ask "Did you mean {project_name}?" first. The core rule "never repeat a name you are unsure of" covers any other name. It does not fix hearing; Deepgram key terms are the STT A/B task.

### Change 8: no caller name

Core rule: no name for the caller, no "sir", no "ma'am", even if the caller gives one. The prompt builder no longer takes `lead_name`, so a later task has to add the parameter on purpose (012).

## Bug: the bot sometimes ends the call after `book_site_visit`

**Verified by reading the code** (`grep` over `agent/`):

- The only code that writes `end_call_tool_invoked=true` is the `end_call` handler (`tools.py:409`). `book_site_visit` writes it `false` (`tools.py:247`). The only other code that stops a call is the disconnect handler (`bot.py:698`), which writes no flag. So a call whose Redis hash shows both `site_visit_booked=true` and `end_call_tool_invoked=true` is a call on which the model chose to call `end_call` (if the hash is as reported).
- The prompt and tool text carry cues that make a booking look like the natural end (table below).

**Not verified** (I have not seen the log lines or the Redis output of the failing call; the "1 of 10" figure is from the brief, and the inbox note gives only counts of 10 bookings and 9 transfers in both batches): *which way* `end_call` was reached. Two paths fit the evidence equally:

- **Path A, same message.** The model emitted `book_site_visit` and `end_call` together in one assistant message (parallel tool calls). `book_site_visit` is `cancel_on_interruption=False`, and per the comment at `tools.py:200-203` the LLM carries on without waiting for the result (I did not re-check this in Pipecat).
- **Path B, next turn.** `book_site_visit` ran alone; the model's follow-up after the tool result (19 of 92 turns in the exit test made such a second LLM call) spoke a confirmation and then called `end_call`, with no new caller utterance in between.

The cues, current wording with line numbers:

| # | Where | Current text | Why it pushes toward `end_call` after a booking |
| --- | --- | --- | --- |
| 1 | `tools.py:350-356` | `END_CALL_OUTCOMES = [ "site_visit_booked", "qualified_interested", "follow_up_needed", "not_interested", "wrong_number" ]` | The `end_call` function lists "site_visit_booked" as one of its own outcomes, pairing booking with hanging up. |
| 2 | `tools.py:444-447` | `"Call this to gracefully close the conversation after achieving a clear outcome."` | A confirmed visit is the clearest outcome of a sales call. |
| 3 | `bot.py:442-443` | `- end_call when the conversation is naturally complete. Do not wait for the caller to hang up.` | Tells the model to hang up itself; a booked visit looks complete. |
| 4 | `bot.py:403` | `- Always end with a clear next step.` | After a booking there is no next step to offer, so the model closes. |
| 5 | `tools.py:252-258` | result is `{"status": "booked", "preferred_date": ..., "preferred_time": ...}` | Unlike `transfer_to_human`, whose result carries `next_step` text (`tools.py:322-326`), the booking result says nothing about the call continuing. `tools.py:244-246` says "a booking is not a call ending", but only a code comment says so. |
| 6 | `tools.py:263-266` | `"Call this when the lead has explicitly agreed to a site visit and provided a date or time preference."` | Silent on whether the call goes on. |

These are reasons the model might do it, not proof of why it did on that call.

**The rewrite covers both paths** (strings only; no handler logic changes). The shared key is "the caller's *latest message* must be a goodbye". On Path A the latest caller message is the day and time, so a same-turn `end_call` is refused by the rule. On Path B there is no new caller message after the booking, so a follow-up `end_call` is refused by the same rule.

1. `END_CALL_SCHEMA.description` (`tools.py:444-447`):

```python
description=(
    "Hang up on the caller. Call this only when the caller's latest message says "
    "goodbye, says they are finished, asks to end the call, or says it is a wrong "
    "number. Never in the same turn as another function, and never in the turn "
    "after a function result unless the caller's latest message already said "
    "goodbye. A booking, a passed-on question or a finished answer is not a reason."
),
```

2. The `outcome` property gets a description and the enum stays (008 owns the tools and may change the outcomes; founder decision 2026-10-23: `site_visit_booked` stays, reachable only through the new `end_call` rule):

```python
"outcome": {
    "type": "string",
    "enum": END_CALL_OUTCOMES,
    "description": "How the call went so far. site_visit_booked only if a visit was booked earlier on this call. It is not a reason to hang up.",
},
```

3. `BOOK_SITE_VISIT_SCHEMA.description` (`tools.py:263-266`):

```python
description=(
    "Call this when the lead has explicitly agreed to a site visit and given a "
    "day or time. Booking a visit does not end the call: keep talking."
),
```

4. The `book_site_visit` result (`tools.py:252-258`) gets the kind of hint `transfer_to_human` already has (covers Path B, where the model reads this result next):

```python
{
    "status": "booked",
    "preferred_date": preferred_date,
    "preferred_time": preferred_time,
    "next_step": (
        "Visit recorded. Confirm the day and time in one sentence. The call is "
        "not over: do not hang up; let the caller lead."
    ),
}
```

The result says "do not hang up" and deliberately does not name `end_call`, because naming a function in a tool result could prime the model to call it.

5. Prompt: the `end_call` bullet in `[CORE RULES]` (above) replaces `bot.py:442-443`; "Always end with a clear next step" (`bot.py:403`) is deleted; the pack's last bullet says the call carries on after a booking.

Limits: all of this is text. It lowers the chance; it cannot guarantee GPT-4o obeys, which is why the exit test has zero tolerance on it. If the exit test still shows it, the next steps (not built now, they overlap 008) are a code guard in `end_call` that refuses when the previous action was a tool result and no new caller turn has arrived, and turning off parallel tool calls for the model (UNVERIFIED whether Pipecat 1.5.0's OpenAI settings expose that). The failing call's own log lines are gone (the PR #39 deploy recreated the container), so we do not wait for them: the exit test copies the `TOOL` lines of any failing call and they tell A from B.

## Data touched

| What | Read or write | By whom | Notes |
| --- | --- | --- | --- |
| `projects.config -> 'payment_plan'` (jsonb object) of the `nxlyr-demo` project, and separately `config -> 'objections' -> 'think_about_it'` and `-> 'price'` | Two `UPDATE ... RETURNING` statements (payment; F05 objections), each filtered by the full project id | 🧑 founder, in the Supabase SQL Editor | Never executed by an agent. Rollback below. |
| `tenants` | Only in the one-line id lookup, as a filter subquery that reads `id`; nothing from `tenants` is returned, `api_key` is never named | 🧑 founder | Never `SELECT *` on it. |
| Redis hash `session:call:<call_sid>` fields `site_visit_booked`, `end_call_tool_invoked`, `transfer_requested`, `call_outcome` | Read only, during the exit test | 🧑 founder | Code writes the same fields as today. |
| Migrations | None | | |

**Facts from your read-only queries (you ran them; recorded here, not re-checked by me):** `projects.tenant_id` exists and `projects.config` is jsonb. Top-level config keys: `pricing, location, overview, amenities, developer, fictional, objections, unit_types, competitors, payment_plan, project_name`. The only payment key is `payment_plan`:

```json
{"name":"25:25:25:25 Construction Linked Plan","tranches":[{"percent":25,"trigger":"Booking Amount"},{"percent":25,"trigger":"Completion of Superstructure"},{"percent":25,"trigger":"Completion of Flooring & Plaster"},{"percent":25,"trigger":"Notice of Possession"}]}
```

**Does anything read `payment_plan`? No (checked by grep).** I searched the whole worktree (excluding `.git`, `venv`, `node_modules`, `.next`) for `payment_plan`, `tranches`, and key reads like `["name"]` / `.get("name"`. Nothing in `agent/` (`tools.py`, `server.py`, `kb_loader.py`, `demo_guard.py`, `bot.py`, the tests), `dashboard/` or `scripts/` reads `payment_plan`, `tranches`, or the plan's `name`. The only reader is the model, which receives the whole KB as one JSON string (`bot.py:406`, `json.dumps(project_kb, indent=2)`). The only KB keys the code reads individually are `developer` and `project_name`, in `bot.py:354, 356`; both lines go away with `[ROLE]` (the JSON still carries them). `kb_loader.py` returns `config` untouched, and `test_kb_loader.py` does not mention `payment_plan`. So keeping `payment_plan` an object, adding a key and changing `name` cannot break code today; it changes only what the model reads.

**Step 1, 🧑 YOU: get the full project id (one line).** It selects `id` only:

```sql
SELECT p.id FROM projects p WHERE p.tenant_id = (SELECT t.id FROM tenants t WHERE t.slug = 'nxlyr-demo');
```

**Step 2, 🧑 YOU: the payment-plan `UPDATE`.** One statement, no `BEGIN`/`COMMIT`. Replace `<full uuid>` with the id from step 1 (the same id in the rollback). It changes only `name` and adds `spoken`; `tranches` is not touched (the `||` operator keeps every other key of the object). The last `AND` makes it apply only to the original value, so running it twice or on an edited plan updates 0 rows and does nothing:

```sql
UPDATE projects p
SET config = jsonb_set(
      p.config,
      '{payment_plan}',
      (p.config -> 'payment_plan') || jsonb_build_object(
        'name', 'Construction Linked Plan',
        'spoken', 'It is a construction linked plan: a quarter at booking, a quarter when the superstructure is done, a quarter when flooring and plaster are done, and the last quarter at possession.'
      )
    )
WHERE p.id = '<full uuid>'
  AND p.config #>> '{payment_plan,name}' = '25:25:25:25 Construction Linked Plan'
RETURNING p.id, p.config -> 'payment_plan' AS payment_plan;
```

👀 VERIFY it returns exactly 1 row, `name` is `Construction Linked Plan`, `spoken` is the sentence, and `tranches` still has four objects with 25 percent each. UNVERIFIED: I have not run this anywhere (no Postgres here). `jsonb_set` with a merged object and `||` on two jsonb objects are standard; the guard on `#>>` returns text.

**Rollback (🧑 YOU, if the plan must go back).** It restores the original object exactly and removes `spoken`:

```sql
UPDATE projects p
SET config = jsonb_set(
      p.config,
      '{payment_plan}',
      '{"name":"25:25:25:25 Construction Linked Plan","tranches":[{"percent":25,"trigger":"Booking Amount"},{"percent":25,"trigger":"Completion of Superstructure"},{"percent":25,"trigger":"Completion of Flooring & Plaster"},{"percent":25,"trigger":"Notice of Possession"}]}'::jsonb
    )
WHERE p.id = '<full uuid>'
RETURNING p.id, p.config -> 'payment_plan' AS payment_plan;
```

**KB cache.** `kb_loader.py:15` caches the KB for 300 s per process. 🧑 After the `UPDATE`, wait 5 minutes before the first exit-test call.

### The F05 knowledge-base `UPDATE` (second `UPDATE`, same style)

F05 is audit finding F05 in `sw_docs/NXLYR-independent-audit.md`, not a script. The prompt half is covered by prompt v2 (P3, P19). The KB half is two strings in the `objections` object, both from your paste:

```text
objections.think_about_it = "Take all the time you need to review with family. I can send the detailed floor plans, pricing sheet, and site video over WhatsApp right away."
objections.price          = "At ₹12,500/sq.ft BSP, Meridian Heights offers private elevator foyers and 80% open greens at a lower cost per sq.ft than neighboring Golf Course Extension projects."
```

- `think_about_it` promises sending that the product cannot do, and "right away" is a timing promise the prompt forbids. New text (founder, 2026-10-23): "Of course, take your time and talk it over with your family. If any questions come up, I'm happy to answer them now." Its apostrophe is doubled (`I''m`) inside the SQL string.
- `price` is a defence of the price with a competitor comparison and digits, which clashes with the pack rule "Do not defend the price". New text (founder, 2026-10-23): "What range were you thinking of?" It is one short question, with no acknowledgement opener (an "I understand" would be filler like "I hear you"). **It contains no digits and no currency sign** (checked: the 32 characters are letters, spaces and one question mark; the `think_about_it` text also has no digits).

**🧑 YOU: run in the Supabase SQL Editor**, with the same `<full uuid>` as the payment `UPDATE`. One statement, no `BEGIN`/`COMMIT`. It sets both paths and is guarded by both exact old texts, so it updates 0 rows if either text differs from your paste (including on a second run); if you get 0 rows, tell me, because the likeliest cause is a character that did not survive the paste (the `₹`, for example). It writes only `{objections,think_about_it}` and `{objections,price}`. `pricing`, the other two objection keys and `payment_plan` are read from the current row and written back as they are, so it does not touch the payment changes whether it runs before or after the payment `UPDATE`:

```sql
UPDATE projects p
SET config = jsonb_set(
      jsonb_set(
        p.config,
        '{objections,think_about_it}',
        to_jsonb('Of course, take your time and talk it over with your family. If any questions come up, I''m happy to answer them now.'::text)
      ),
      '{objections,price}',
      to_jsonb('What range were you thinking of?'::text)
    )
WHERE p.id = '<full uuid>'
  AND p.config #>> '{objections,think_about_it}' = 'Take all the time you need to review with family. I can send the detailed floor plans, pricing sheet, and site video over WhatsApp right away.'
  AND p.config #>> '{objections,price}' = 'At ₹12,500/sq.ft BSP, Meridian Heights offers private elevator foyers and 80% open greens at a lower cost per sq.ft than neighboring Golf Course Extension projects.'
RETURNING p.id,
          p.config -> 'objections' AS objections,
          p.config -> 'pricing' AS pricing,
          p.config -> 'payment_plan' AS payment_plan;
```

👀 VERIFY it returns exactly 1 row; `objections` still has its four keys (`price`, `location`, `think_about_it`, `possession_timeline`), with `think_about_it` and `price` showing the new texts and `location` and `possession_timeline` unchanged; `pricing` is exactly as you saw it before; `payment_plan` is whatever the payment `UPDATE` left (the original object if it has not run yet, the new object with `spoken` if it has).

**Before-values saved.** Both old texts are the pasted lines above, and both are embedded in the guard and in the rollback below.

**Rollback (🧑 YOU, if needed).** One statement that restores both original texts and nothing else:

```sql
UPDATE projects p
SET config = jsonb_set(
      jsonb_set(
        p.config,
        '{objections,think_about_it}',
        to_jsonb('Take all the time you need to review with family. I can send the detailed floor plans, pricing sheet, and site video over WhatsApp right away.'::text)
      ),
      '{objections,price}',
      to_jsonb('At ₹12,500/sq.ft BSP, Meridian Heights offers private elevator foyers and 80% open greens at a lower cost per sq.ft than neighboring Golf Course Extension projects.'::text)
    )
WHERE p.id = '<full uuid>'
RETURNING p.id,
          p.config -> 'objections' AS objections,
          p.config -> 'pricing' AS pricing,
          p.config -> 'payment_plan' AS payment_plan;
```

**After both `UPDATE`s, 🧑 YOU, read-only check** that no other string in the KB still promises sending (the leading spaces keep it from matching "present" or "consent"; UNVERIFIED, not run anywhere):

```sql
SELECT jsonb_path_query(
         p.config,
         'strict $.** ? (@.type() == "string" && @ like_regex "(whatsapp|brochure|e-?mail|right away| send| sent)" flag "i")'
       ) AS still_matching
FROM projects p
WHERE p.id = '<full uuid>';
```

Zero rows is the pass. A hit is a KB string I have not seen; paste it and I will write a third guarded `UPDATE` in this style. Order after the merge: the two `UPDATE`s in either order, then the 5-minute cache wait, then the smoke call. The exit-test step 7 ("that sounds expensive") is where the new `price` text is checked.

## Acceptance tests (automated)

New file `agent/test_prompt.py`, `unittest`, no network. The prompt tests do not import Pipecat; the tools tests import `tools`, which does (the venv has it). Run, from the worktree:

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"; PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_prompt
"$PY" -m unittest agent.test_turn_release agent.test_ws_auth agent.test_log_hygiene agent.test_demo_guard
"$PY" -m unittest agent.test_kb_loader
(cd agent && "$PY" -c "import server, week2_latency_observer")
```

`test_kb_loader` has 5 known errors on `main` (F23); the PR must show it still has exactly those 5 and no more.

Prompt tests build from a fixed KB dict `{"project_name": "Test Heights", ...}` and run for both lead sources and both disclosure modes where it matters.

| # | Test | Checks |
| --- | --- | --- |
| P1 | Three blocks | `[CORE RULES]`, `[REAL ESTATE PACK]`, `[COMPANY]` each appear exactly once, in that order, before `[CURRENT DATE]`. `[ROLE]`, `[PERSONA CONTEXT]` and `[CONVERSATION EXAMPLES]` are absent. |
| P2 | Banned phrases | For each phrase in `BANNED_OPENERS` (whole word, case-sensitive), zero matches in the prompt once the one `Never open a reply with:` line is removed, and zero in every greeting and in `CLOSING_PHRASE`. |
| P3 | Samples | Every `You:` line in `[HOW IT SOUNDS]` has no banned phrase and no digit, `Rs`, `₹`, "send", "WhatsApp", "brochure", "shortly" or "soon"; at most 3 of 4 end in `?`; the answer to "Hello?" is at most five words. |
| P4 | Disclosure | Exactly one `AI DISCLOSURE` paragraph; it contains "answer at once and truthfully", "Never deny it" and "never claim to be human". "Never reveal" and "not an AI" are absent. With `on_ask` the greetings have no "AI"; with `upfront` they have "AI assistant" and the paragraph is the up-front one; any other mode raises `ValueError`. The `on_ask` paragraph contains the exact sentence `"I'm an AI assistant calling for Next Layer."` and no `"Yes, I'm an AI"`. None of the 4 sample exchanges in `[HOW IT SOUNDS]` is about AI disclosure, so there is no sample to change. |
| P5 | Greeting templates | `demo_form`: contains "Aarya", "Next Layer", "demo call" and the sample project name exactly once; three sentences. `lead` with a project: names it once; `lead` without: names no project and says "the enquiry you sent in". Unknown source raises `ValueError`. |
| P6 | No end-after-booking text | No regex hit for `(book|visit)[^.\n]{0,80}end_call` or `end_call[^.\n]{0,80}(book|visit)` outside the "is not the end" sentence; absent: "naturally complete", "Do not wait for the caller to hang up", "clear next step". Present: "latest message" and "Never call end_call in the same turn as another function". |
| P7 | Tool strings | `END_CALL_SCHEMA.description` lacks "clear outcome" and contains "goodbye", "latest message" and "same turn"; `BOOK_SITE_VISIT_SCHEMA.description` contains "does not end the call"; the `outcome` property has a `description`; `END_CALL_OUTCOMES` is unchanged (`site_visit_booked` stays, reachable only through the new `end_call` rule). |
| P8 | Booking result | Run `book_site_visit` with a fake `FunctionCallParams` (resources `None`, `preferred_date` = today); the result has `status == "booked"` and a `next_step` containing "do not hang up" and not containing "end_call". |
| P9 | Closing phrase | `tools.CLOSING_PHRASE is prompt.CLOSING_PHRASE`; no digits, no promise words. |
| P10 | Names | "Never use a name for the caller" appears once; `sir` and `ma'am` appear only inside that rule; `build_system_prompt` has no `lead_name` or `agent_name` parameter. |
| P11 | Speech and gender rules | The prompt contains the words rule and the payment rule (the "spoken" line and "Never read it out as a ratio; say it as a sentence"); the string `25:25:25:25` is **absent** from the assembled prompt (outside the KB JSON); it contains "You are Aarya, a woman"; it contains no Hindi (`rahi`, `karungi`, `raha`, `karunga`). |
| P12 | Size | Prompt with an empty KB is at most 4,900 characters (builder's measurement 4,790; today 4,662). Guards the "not slower" goal. |
| P13 | Greeting appears once | For each lead source and disclosure mode, `build_initial_messages()` returns exactly `[system, assistant]`, and the greeting string occurs exactly once across all message contents (the system prompt does not quote it). |
| P14 | No unresolved placeholders | Remove the rendered KB JSON from the prompt, then no `{...}`, no `<...>`, no `None`, no `[Name]`-style tokens, and every `[...]` token is one of the section headers. `build_system_prompt` with a KB lacking `project_name` still renders cleanly (fallback wording). |
| P15 | Names that must not be spoken | Case-insensitive "nxlyr" and "neha" are absent from the whole assembled prompt, from every greeting, from `CLOSING_PHRASE`, and from every `You:` sample line. "Next Layer" is present in the prompt, and the `[COMPANY]` block contains "If they ask which company, say Next Layer". (This tests the text; whether the model obeys is the exit test.) |
| P16 | Persona gone | "persona" (case-insensitive) is absent from the prompt; `build_system_prompt` has no `persona_context` parameter. |
| P17 | Greeting frame | Source-level check that `bot.py` contains `TTSSpeakFrame(greeting, append_to_context=False)`, builds the context from `build_initial_messages`, and does not mention `lead_source=LEAD_SOURCE_LEAD`. Brittle by design; the exit test is the real proof. |
| P18 | Lead template unreachable | `inspect.signature(bot.run_bot)` has no `lead_source` parameter. (Skip if importing `bot` is too heavy; it is not for `test_turn_release`, which imports it already.) |
| P19 | No promise to send | Take the assembled prompt, remove the rendered KB JSON, the sentence "You cannot send brochures, WhatsApp messages, emails or links, and you never offer to." and the bullet that lists the banned timing words; then none of `brochure(s)`, `whatsapp`, `email`/`e-mail`, `link(s)`, `send`, `sends`, `sending`, `sent` (whole word, case-insensitive) is left. Also true for every greeting, the closing phrase and every `You:` sample line. |

These tests check the assembled text only. They cannot show that GPT-4o obeys it; the exit test does that.

Optional, non-gating, 🧑 YOU (needs `OPENAI_API_KEY` and Supabase credentials, which only you handle): run `prompt_harness.py` with the first nine script steps and paste the transcript in the PR. It uses the real model with the real tools and shows whether a booking is followed by `end_call` in text mode. The harness has no interruptions, so it says nothing about the greeting.

## Exit test (what the founder does by hand)

**Before the build, 🧑 YOU: listening test.** In the ElevenLabs web app, search the voice library for "Neha P" (labelled "Neha P - Relatable Sales Agent"; that label is internal, the spoken name stays Aarya). Paste the demo greeting from Change 2 and the closing phrase, use ElevenLabs Flash v2.5 (production, per the founder: ElevenLabs HTTP TTS, `eleven_flash_v2_5`, voice "Neha P"; nothing in this spec changes for other models), and 👀 VERIFY it says "Next Layer" as two words and that the three-sentence greeting is not tedious. If the pronunciation is wrong, change `COMPANY_SPOKEN` before the build.

**Order after the merge (🧑 YOU, then 👀 VERIFY each):**

1. The merge deploys. Check the deploy and the container, twice:

```bash
gh run list --workflow=deploy.yml --limit 1
ssh nxlyr-vps "docker ps --format '{{.Names}} {{.Status}}'"
```

   Run the `docker ps` line again 10 s later. 👀 The latest `deploy.yml` run is green for the merge commit and the agent shows healthy both times.
2. Run the two `UPDATE`s from "Data touched" (the payment plan and the F05 knowledge-base string, either order), then the read-only check. 👀 Each returns what is described there.
3. Wait 5 minutes (KB cache).
4. Smoke call: pick up and say two or three words. Copy the events log and read the instance numbers:

```bash
ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/"
scp nxlyr-vps:/tmp/section6_real_call_events.log ./events.log
ssh nxlyr-vps "rm -f /tmp/section6_real_call_events.log"
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events.log --md
```

   👀 VERIFY the header reads `instances 0-0` (the smoke call is instance 0 after a fresh deploy, because instance numbers restart; if it reads anything else, the container was not fresh, so use what you see). **N = the last instance number + 1**, expected 1. Also 👀 VERIFY the log has `prompt v2: chars=... lead_source=demo_form disclosure_mode=on_ask company=NXLYR`, that the voice says "Next Layer", and that it speaks the demo greeting.

**Setup** (same as the baseline, "How to reproduce"):

```bash
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HSET demo:config phone_limit 100 ip_limit 100 phone_cooldown_seconds 5 ip_cooldown_seconds 5"
T0=$(date -u +%Y-%m-%dT%H:%M:%SZ); echo "$T0"
```

**Part A, 10 script calls**: the baseline's 11-step script plus one payment question (step 7a), one call at a time, 10 s apart, same phone and room. Step 1 has two variants:

1. Say "hello". **Calls 1-5:** say it the moment you pick up, over the greeting. **Calls 6-10:** wait for the greeting to finish, then say it.
2. Answer "yes". 3. Long answer with a 0.7 s pause. 4. "Around one point two crore". 5. Name the project. 6. Talk over the bot once. 7. "That sounds expensive". **7a. Ask "what's the payment plan?"** 8. Ask it to WhatsApp the details. 9. Ask for a Saturday 11 am site visit. 10. Ask for a real person. 11. Silent 6 s, hang up.

**What a pass sounds like at step 7 ("that sounds expensive").** A short reply that asks what range the caller has in mind, for example "What range were you thinking of?", which is what the knowledge base now says. It does not open with an acknowledgement ("I understand", "I hear you", "Fair question" and the like count as filler), does not compare with other projects, does not list features to justify the price, does not say the project is cheaper or better value, does not restate the rate unprompted, and says any amount in words (never digits, never "Rs"). A miss: any filler opener, any competitor comparison, any defence, or no question about range. This is recorded in the scoring sheet and counts toward "natural"; say if you want it as a separate gate.

Step 7a adds one turn per call to the latency sample; the p50 comparison stays valid. On calls 1, 4, 7 and 10 also time, by stopwatch, pickup to the bot's first word (data, not a gate).

After the 10th call, before Part B, copy the events log and run the flag check (the session hashes live 4 hours):

```bash
ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/"
scp nxlyr-vps:/tmp/section6_real_call_events.log ./events.log
grep -cE '[0-9]{10}' ./events.log
ssh nxlyr-vps "rm -f /tmp/section6_real_call_events.log"
ssh nxlyr-vps 'for k in $(docker exec nxlyr_redis redis-cli --scan --pattern "session:call:*"); do echo "$k"; docker exec nxlyr_redis redis-cli HMGET "$k" site_visit_booked end_call_tool_invoked transfer_requested call_outcome; done'
grep -c "TOOL end_call" ./events.log
grep "TOOL book_site_visit" ./events.log | grep -o "call_sid=[^ ]*" | sort | uniq -c
```

The `grep -c` must print 0. Expected for each of the 10 calls, in `HMGET` order: `true`, `false`, `true`, and a blank `call_outcome` (only `end_call` sets it, and no script line says goodbye, so `end_call` should not fire at all). **Any call showing `end_call_tool_invoked` = `true` fails the gate.** Redis alone can miss the bug: audit finding F16 says an outstanding asynchronous booking can overwrite a later end flag with `false`. So the log is a second gate: `grep -c "TOOL end_call"` must print **0** for Part A (no script line says goodbye). The last command counts `TOOL book_site_visit` lines **per call** (one line of output per `call_sid`, with its count). Pass: 10 distinct `call_sid`s, each with a count of 1 or more. A call that booked twice shows 2, which is not a failure; a call with no line at all does not appear in the output, so fewer than 10 output lines is a failure. UNVERIFIED: that the `call_sid=` text survives the 004 log scrubber; if the output is empty, list `grep "TOOL book_site_visit" ./events.log` with timestamps and group the lines into calls by hand. A key with `site_visit_booked` = `true` and no `transfer_requested` is the bug's signature. 👀 VERIFY you see 10 keys; if there are more, ignore keys last written before T0 (a key's TTL is 14400 minus its age in seconds). For any failing call, copy its `TOOL book_site_visit` / `TOOL end_call` lines with timestamps from `./events.log`; they say whether `end_call` came in the same message as the booking (Path A) or the next turn (Path B).

Latency, from the same log, with the N you read after the smoke call:

```bash
python3 "/Users/vansh/Desktop/SALES AGENT/tools/latency_report.py" ./events.log --from-call N --md
```

**Part B, 5 more calls**, after the report is run (the script has no `--to-call`, so these must not be in that log):

- Calls 11-12, silent: pick up and say nothing for 30 s, then hang up. 👀 The greeting plays exactly once and the bot says nothing else.
- Calls 13-14, "are you a bot?": call 13, say "hello", then right after the greeting ask "are you a bot?"; call 14, have the normal conversation to step 5, then ask "are you a bot?". 👀 The answer is immediate and plain, in a few words: "I'm an AI assistant calling for Next Layer" (it may name the company); the call then carries on.
- **Call 15, goodbye after a booking** (the one call where hanging up is the right outcome): say "hello" after the greeting, run steps 2 to 9 of the script up to and including the Saturday 11 am booking, then say "okay, thanks, bye". Expect, 👀 by ear, the closing phrase "Thanks for your time. Have a good day." exactly once and then the call ends, with no extra question after the goodbye. Then run the log and Redis checks below for this call. Expect: **exactly one `TOOL end_call` line in the whole log since T0** (Part A had 0, calls 11-14 end by you hanging up, so call 15 supplies the one), and the call's Redis hash shows `site_visit_booked=true`, `end_call_tool_invoked=true` and a `call_outcome` value.

```bash
ssh nxlyr-vps "docker cp nxlyr_agent:/app/section6_real_call_events.log /tmp/"
scp nxlyr-vps:/tmp/section6_real_call_events.log ./events.log
ssh nxlyr-vps "rm -f /tmp/section6_real_call_events.log"
grep -c "TOOL end_call" ./events.log
```

The count must print **1**. For the Redis side, re-run the `HMGET` loop from above and read the new key (the one whose `end_call_tool_invoked` is `true`).

Also on any one call, ask "which company is this?" and 👀 hear "Next Layer".

Then the leak regression, and restoring the limits (the leak script asks for the last six digits of the test phone; run it on its own line):

```bash
"/Users/vansh/Desktop/SALES AGENT/tools/leak_counts.sh" "$T0"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli DEL demo:config"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli HGETALL demo:config"
ssh nxlyr-vps "docker exec nxlyr_redis redis-cli GET demo:kill"
```

Both reads must be empty; every leak gate 0 as after 004. Expected counts since T0 (the 004 pass criteria): `finished` of at least 15 (10 Part A calls plus 5 Part B calls) and `masked` of at least 15.

**Scoring sheet** (🧑 YOU, one row per call, 15 rows; the first two columns are evidence for the second-greeting cause, the stopwatch is data):

| Call | Hello variant (over greeting / after greeting / n.a.) | Pickup to first word, s (calls 1, 4, 7, 10) | Natural? Y/N | Filler opener | Echo of one-word answer | Lists facts / question on every line | Full project name repeated | Digits or "Rs" spoken | Price objection handled (step 7) | Payment plan said as a sentence (step 7a) | Used a name / sir / ma'am | AI denied or dodged | Ended after booking | Second greeting |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Calls 1-5 are "over", calls 6-10 "after", calls 11-14 "n.a." and call 15 "after". If a second greeting shows up only on calls 1-5 it points at an interrupted greeting (H1); only on 6-10, a full one (H2); on both, both. For reference, the greeting stopwatch was 3.0 / 3.75 / 4.9 / 3.8 s in the baseline and 6 / 3 / 3 / 2.8 s in the 011 exit. Add one overall note: is the three-sentence demo greeting tedious by ear? Not a gate.

**Pass bar.**

1. At least **7 of the 10** script calls feel natural by ear (the original plan's bar).
2. **Zero tolerance across all 15 calls**: an invented name (or "sir" or "ma'am"); denying or dodging that it is an AI; ending the call after a booking *without the caller saying goodbye* (any of calls 1-14 with `end_call_tool_invoked=true`, checked with the Redis command above, or that drops after the booking confirmation); a second greeting (a repeated introduction or greeting after the opening, on any call including the two silent ones). One occurrence fails the test.
3. **Goodbye after a booking (call 15)**: exactly one `TOOL end_call` line in the log since T0, the closing phrase heard once, and the call ends. Zero lines, or two or more, fails: it proves `end_call` still works when the caller is really done.
4. **Payment plan, a hard gate**: at step 7a the bot says the plan as a sentence. Across the 10 Part A calls, **0 or 1 miss passes; 2 or more fails**. A miss is reading it out as "twenty-five, twenty-five, twenty-five, twenty-five" or "twenty-five colon…" instead of as a sentence.
5. **Latency**, from `latency_report.py` on Part A, against the 23 Oct exit test with 10% allowed: LLM first token **p50 at most 716 ms** (651 ms + 10%) and first-sentence wait **p50 at most 84 ms** (76 ms + 10%). If either misses, rerun the 10 calls once; the rerun decides. No p95 gate. The two base figures come from the 23 Oct exit-test report you ran; they are not in `docs/baselines/2026-10-23-011-exit.md`, and you can recompute them from your saved events.log with `latency_report.py`.
6. Leak gates all 0 and the events log holds no ten-digit number.

The zero-tolerance items apply to the rerun too: one occurrence in any run fails. Paste the scoring sheet, the Redis output, the report and the leak counts into the PR's Evidence section. A failed bar means no memory close-out, and the revert below.

## Risks and rollback

| Risk | Likelihood / effect | Mitigation |
| --- | --- | --- |
| Terse prompt makes the bot curt, passive or unhelpful | Medium. The natural-by-ear bar may fail | Four sample replies model the target; rules say a question is fine when it moves things on. Tune the text after the first batch; no code change. |
| Naming banned phrases primes the model, or it swaps in other fillers ("Okay", "Of course", "Alright", "Understood") | Medium | The list is one tuple; extend it after hearing the calls. The rule also says "not a reaction" in general. |
| The `end_call` fix does not hold (the model still hangs up after a booking, by Path A or B) | Low to medium | The Redis gate catches it with zero tolerance, and the `TOOL` lines say which path. Next step: a code guard in `end_call` and parallel tool calls off (with 008). |
| Seeding the greeting: if the caller's "hello" cancels it before any word is heard, the model believes it introduced itself | Low (UNVERIFIED how often) | The "who are you / why did you call" prompt rule; the two hello variants in the exit test tell us how often. |
| The `lead` greeting is untestable on a real call | Certain, by design | `run_bot()` takes no `lead_source`, so the `lead` template cannot be reached on a real call until task 012 adds the plumbing (P18). Unit tests P5 and P13 cover it meanwhile. |
| For real leads who enquired with a developer, naming "Next Layer" may be untrue once there are tenants | Not today (no real-lead path) | Company values are per-deployment constants; making them per-tenant belongs to the task that adds the lead path. |
| "Next Layer" sounds odd in the voice | Low | `COMPANY_SPOKEN` is one constant; the listening test happens before the build. |
| AI-disclosure `on_ask` may not satisfy TRAI/DPDP; the lawyer has not answered | Unknown | Not a claim of compliance anywhere. One constant switches it; test P4 covers both modes. |
| Latency regresses: prompt about 35 tokens longer; shorter replies should shorten the first-sentence wait | Low | P12 caps the size; the exit test measures both p50s against the 10% bar. |
| Merge conflicts: L1 edits the same file (`run_bot()` / `on_client_connected`, `bot.py:678-693`), and 008 edits `tools.py` | Medium | Prompt moves to `prompt.py`, so the shared hunk is about 15 lines. Whichever merges second takes `origin/main` and reruns all five test modules (`patterns.md`). |
| The KB still promises WhatsApp or brochures, or the plan still reads "25:25:25:25", and the model repeats it | Medium until the SQL runs | F05 and the payment `UPDATE` run after the merge and before the exit test; the 5-minute cache wait; the guarded `UPDATE` returns 0 rows if the plan is not in its original state. |
| The model reads the `percent: 25` digits in `tranches` as "twenty-five, twenty-five…" despite the `spoken` line | Low to medium | Prompt rule plus the `spoken` key; exit-test item 3 checks it on every script call. |
| `test_prompt.py` ships in the image (`COPY *.py`), like `test_turn_release.py` (inbox `2026-10-22-test-turn-release-ships-in-the-image.md`) | Cosmetic | Accepted, same as 011. |

**Rollback.** There is no runtime flag for the prompt (I am deliberately not adding a config system), so rollback is a revert: 🧑 YOU `git revert -m 1 <merge commit>` on a task branch, open the PR, merge, and `deploy.yml` redeploys (`git pull` and `docker compose up -d --build` as one step, rule 2). Check the container twice afterwards. For a call-quality emergency with no deploy, the demo kill switch still works: `ssh nxlyr-vps "docker exec nxlyr_redis redis-cli SET demo:kill 1"` (clear with `DEL`). The KB changes do not depend on the code: the payment-plan rollback `UPDATE` is in "Data touched", and the new prompt reads the old plan fine (it falls back to the percentages, which the prompt tells it to say as words).

## Open questions for me (the founder)

Answered on 2026-10-23 and built into this revision: the `think_about_it` wording; the `objections.price` wording ("What range were you thinking of?"), in one combined guarded `UPDATE` with one rollback for both original texts; `TOOL book_site_visit` counted per call; the build-review changes of r6.

Nothing is open for the founder in this spec. The two things that remain unverified are listed under "UNVERIFIED" near the top: the SQL has not been run anywhere, and the `call_sid=` text in the `TOOL` log lines has not been checked against the 004 scrubber.
