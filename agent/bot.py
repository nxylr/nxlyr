"""
NXLYR — Exotel telephony voice bot (Week 3 / Task 2.3)

Exotel media-stream WebSocket -> Deepgram STT -> GPT-4o -> ElevenLabs TTS -> back
out over the same WebSocket.

Ported from agent/test_pipeline.py (the Week 2 local mic/speaker smoke test).
What changed in the port, and why:

  - LocalAudioTransport -> FastAPIWebsocketTransport, with an ExotelFrameSerializer
    built by hand from the `start` event. We deliberately do NOT use
    pipecat.runner.utils.create_transport() (which the official example uses and
    which would build the serializer for us) — the manual path is explicit about
    what it wires up and lets us skip the `runner` extra entirely.

  - 8000 Hz end-to-end, was 22050. Exotel's media stream is 8 kHz, and
    ElevenLabs can synthesize straight to pcm_8000, so there is no resample
    stage anywhere in the audio path.

  - MicGateDevOnly is gone. It existed only because a local speaker+mic setup
    feeds the bot's own TTS back into the mic; Exotel gives us separate in/out
    legs, so there is no echo path to gate.

  - PipelineTask/PipelineRunner -> PipelineWorker/WorkerRunner, the current
    (non-deprecated) construct-and-run API in Pipecat 1.5.0.

  - main() -> run_bot(websocket), invoked once per call by server.py's /ws route.
    The aiohttp session that ElevenLabsHttpTTSService needs is scoped to one
    call rather than to the whole process.

Requires environment variables (see .env.template):
  DEEPGRAM_API_KEY
  OPENAI_API_KEY
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID   (optional — defaults to a stock ElevenLabs voice)
  ELEVENLABS_MODEL      (optional — defaults to eleven_turbo_v2)
  NXLYR_LATENCY_CSV     (optional — enables the Week 2 latency observer)
  LOG_LEVEL             (optional — defaults to DEBUG)
"""

import json
import os
import sys

import aiohttp
from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import WebSocket

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
# Switched from ElevenLabsTTSService (WebSocket) to ElevenLabsHttpTTSService (HTTP):
# on this Hetzner/Docker setup the websocket connection went unhealthy after the
# first turn with no error logged (matches known Pipecat websocket-reconnect
# issues), silently killing TTS for the rest of the run. HTTP is the Pipecat-docs
# recommended fallback for "when WebSocket connections are not possible" and our
# test has no interruption/word-timestamp needs that would require the websocket.
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService, ElevenLabsHttpTTSSettings
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_start import (
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

# Bare logger.remove() rather than test_pipeline.py's logger.remove(0): this module
# is imported by a long-lived server, and remove(0) raises if the default handler
# is already gone.
logger.remove()
logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "DEBUG"))

REQUIRED_ENV_VARS = ["DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"]

# Exotel streams 8 kHz 16-bit signed little-endian mono PCM ("raw/slin"),
# base64-encoded per media event — no mu-law/G.711 companding anywhere, unlike
# the Twilio path (twilio.py:294 calls ulaw_to_pcm; exotel.py has no equivalent).
# Everything downstream is pinned to the same rate so no resampling happens
# between us and the carrier.
EXOTEL_SAMPLE_RATE = 8000


def check_env():
    """Raise (rather than sys.exit) — this runs inside a request handler now."""
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")


# Named rather than inlined into OpenAILLMService.Settings below so
# prompt_harness.py (Task 2.3's text-only harness) can import the exact
# production values instead of duplicating them and risking drift.
LLM_MODEL = "gpt-4o"
LLM_MAX_TOKENS = 160
LLM_TEMPERATURE = 0.75


# The tenant this bot serves. Single-project for now (Week 4 scope); becomes
# a per-call parameter once server.py routes more than one tenant.
KB_PROJECT_SLUG = "nxlyr-demo"


def load_project_kb() -> dict:
    """Load the real project KB from Supabase (agent/kb_loader.py, Task 3.1).

    Shared by run_bot() and prompt_harness.py so both go through the exact
    same KB-loading behavior. kb_loader.load_kb() fails loudly (raises) on a
    missing/invalid KB — that exception is left to propagate to the caller
    rather than caught and downgraded to {}, since neither a real call nor a
    prompt-harness run is meaningful on an empty KB.
    """
    from kb_loader import load_kb

    return load_kb(KB_PROJECT_SLUG)


# Week 4 targets only the end-user persona (Implementation Plan §Week 4,
# "System prompt v1 — end-user persona"); PRD §6.2's continuous scoring model
# and reclassification logic are Week 5 (C-01/C-02) and don't exist yet. This
# is the static stand-in TRD §3.2's [PERSONA CONTEXT] block reads from until
# then — same shape PRD §6.2 defines for the real thing, so Week 5 only has to
# swap in live per-turn scores, not touch the prompt structure.
DEFAULT_PERSONA_CONTEXT = {
    "end_user": 1.0,
    "investor": 0.0,
    "land_buyer": 0.0,
}

# Generic property-sales turns for TRD §3.2's [CONVERSATION EXAMPLES] block.
# Deliberately not Meridian Heights-specific — Section 3's KB isn't merged yet.
FEW_SHOT_EXAMPLES = [
    (
        "What's the price for a 3 BHK?",
        "Depends a bit on the tower and floor, but I can get you exact numbers — "
        "are you looking at this for yourself, or as an investment?",
    ),
    (
        "Can you send me a brochure?",
        "Sure, I'll have that sent right after this call. While I have you — "
        "what's prompting the search, a new home or just exploring for now?",
    ),
    (
        "This sounds expensive.",
        "Fair question. The payment plan alone is pretty flexible, and once "
        "you see everything laid out it tends to make a lot more sense. Want "
        "me to send over the full breakdown?",
    ),
]


def build_system_prompt(
    *,
    agent_name: str = "the assistant",
    developer_name: str | None = None,
    lead_name: str = "the caller",
    project_name: str | None = None,
    project_kb: dict | None = None,
    persona_context: dict | None = None,
) -> str:
    """Assemble the system prompt from TRD §3.2's modular blocks.

    Replaces the old hardcoded 3-line string. `project_kb` and
    `persona_context` both default to placeholders so this is callable
    standalone (e.g. from a mock call) without Section 3's KB or Week 5's
    persona detector — see the module-level comments on each default for why.
    """
    project_kb = project_kb or {}
    persona_context = persona_context or DEFAULT_PERSONA_CONTEXT
    leading_persona = max(persona_context, key=persona_context.get)
    persona_confidence = persona_context[leading_persona]

    role = (
        f"You are {agent_name}, a pre-sales representative at "
        f"{developer_name or project_kb.get('developer', 'the developer')}.\n"
        f"You are calling {lead_name} who filled in an enquiry form about "
        f"{project_name or project_kb.get('project_name', 'the project')}.\n"
        "IMPORTANT: say every name and detail above exactly as written, as "
        'natural spoken words. If a detail reads as generic (like "the '
        'developer" or "the project"), that IS the real value to say out '
        "loud — it is not a placeholder waiting to be filled in. Never "
        'invent a specific name, and never output a bracketed or templated '
        'field such as "[Developer Name]" or "[Company Name]".'
    )

    # Extends TRD §3.2's RULES block in two places (otherwise verbatim,
    # including the acknowledgement-variation rule and the no-lists rule):
    #
    # 1. The plain "under 3 sentences" instruction wasn't holding under
    #    objection pressure — RATING_v1.md caught 03_objection_heavy.txt at 4
    #    sentences twice and 05_wrong_number.txt once, all three while the
    #    model was reassuring/apologizing at length before making its point.
    #    Added a concrete too-long/correct-length pair so there's something
    #    to pattern-match against, not just an abstract count.
    # 2. RATING_v1.md also flagged "strong track record" / "highest quality
    #    construction" as confident, unbacked claims — the same underlying
    #    risk as inventing a price, just not a number. Added a rule that
    #    routes reputation/quality claims through the same defer-if-you-don't-
    #    have-it discipline already applied to prices and dates.
    rules = (
        '- Speak naturally. Use "Right", "Sure", "Got it" as acknowledgements.\n'
        "- Keep each response under 3 sentences. This is a phone call.\n"
        '  Too long: "Right, I hear you. While some projects might promise quicker '
        "possession, our timelines ensure the highest quality construction and "
        "attention to detail. Plus, the amenities and location really make the wait "
        'worthwhile. Would you be interested in visiting the site?" (4 sentences — '
        "reassures three times before making the offer.)\n"
        '  Correct: "Right, I hear you — the wait buys you quality construction. Want '
        'to see the site for yourself?" (2 sentences, same offer, said once.)\n'
        "- Never read out a list. Speak in natural flowing sentences.\n"
        "- Never reveal you are an AI.\n"
        "- If asked about pricing, first build value, then state range.\n"
        "- Never give discounts or make promises not in the project config.\n"
        '- Never claim a reputation, track record, or quality standard (e.g. "strong '
        'track record", "highest quality", "excellent reputation") unless it is a '
        "specific fact from the project knowledge base. If you don't have one, "
        "redirect to something concrete you do have, or defer — the same way you "
        "already defer on prices and dates.\n"
        "- Always end with a clear next step."
    )

    kb_block = json.dumps(project_kb, indent=2) if project_kb else "(none loaded yet)"

    persona_block = (
        f"Current leading persona: {leading_persona} (confidence: {persona_confidence:.2f})\n"
        # Question sets and field-capture tracking (PRD §6.3, TRD §3.4) don't
        # exist yet either — static text until that lands alongside Week 5.
        "Active question set: end-user (budget, timeline, family needs, location)\n"
        "Fields still to capture: (none tracked yet)\n"
        "Reclassification trigger: False\n"
        "  → If true: ask the confirming question before switching question sets.\n"
        '    "You mentioned [signal] — are you looking at this as an investment,\n'
        '     or primarily for your own use?"'
    )

    examples_block = "\n\n".join(f"Buyer: {q}\nYou: {a}" for q, a in FEW_SHOT_EXAMPLES)

    # References tools by name only — TRD §3.5 already specifies their schema,
    # and the actual handlers are Section 2/Task 2.1, gated behind Section 4.
    tools_block = (
        "Use book_site_visit when the lead agrees to visit.\n"
        "Use end_call when the conversation is naturally complete.\n"
        "Use transfer_to_human when the query is outside your scope."
    )

    return (
        f"[ROLE]\n{role}\n\n"
        f"[RULES]\n{rules}\n\n"
        f"[PROJECT KNOWLEDGE BASE]\n{kb_block}\n\n"
        f"[PERSONA CONTEXT]\n{persona_block}\n\n"
        f"[CONVERSATION EXAMPLES]\n{examples_block}\n\n"
        f"[TOOLS]\n{tools_block}"
    )


# Fixed opening line, pushed directly as a TTSSpeakFrame on connect rather than
# left for the LLM to improvise from the system prompt (see on_client_connected
# for why — the improvised version caused a real bug) or baked into the system
# prompt as a standing directive (tried once, reverted — a permanent per-turn
# instruction isn't a first-turn-only one).
GREETING = (
    "Hi, thanks for your interest — I'm calling about the enquiry you sent in. "
    "Have you got a couple of minutes to chat?"
)


async def run_bot(websocket: WebSocket) -> None:
    """Run one call's pipeline to completion over an accepted Exotel WebSocket.

    server.py's /ws route accepts the socket and hands it here. Returns when the
    call ends; the caller is responsible for closing the socket.
    """
    check_env()

    # Consume Exotel's handshake (`connected` + `start`) to get the identifiers the
    # serializer needs. This is cached on the websocket by Pipecat, so it's safe
    # even though websocket.iter_text() is a single-use stream.
    transport_type, call_data = await parse_telephony_websocket(websocket)
    if transport_type != "exotel":
        raise RuntimeError(
            f"Expected an Exotel media stream, got transport type {transport_type!r}"
        )

    stream_sid = call_data.stream_id
    call_sid = call_data.call_id
    if not stream_sid:
        raise RuntimeError("Exotel start event carried no stream_sid")

    logger.info(f"Exotel call connected — stream_sid={stream_sid} call_sid={call_sid}")

    # Loaded before any STT/LLM/TTS setup: the call cannot proceed on a
    # missing or invalid KB, so there's no point paying for that setup first.
    # load_project_kb() raises on failure (kb_loader's fail-loud design) —
    # re-raised here after a KB-specific log line, so it's clear from the
    # logs *what* aborted the call rather than just that something did.
    # server.py's /ws handler already wraps run_bot() in a try/except that
    # logs the full traceback and closes the websocket gracefully (including
    # the case where Exotel has already hung up), so that's left to do the
    # actual close rather than duplicating it here.
    try:
        project_kb = load_project_kb()
    except Exception as e:
        logger.error(
            f"Project KB failed to load for slug={KB_PROJECT_SLUG!r} "
            f"(call_sid={call_sid}) — aborting call: {e}"
        )
        raise

    serializer = ExotelFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        params=ExotelFrameSerializer.InputParams(
            exotel_sample_rate=EXOTEL_SAMPLE_RATE,
            # None means "follow the pipeline's rate" — which we also pin to 8000
            # below, so this stays a straight pass-through.
            sample_rate=None,
        ),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=EXOTEL_SAMPLE_RATE,
            audio_out_sample_rate=EXOTEL_SAMPLE_RATE,
            # Telephony frames are raw payloads, never WAV-wrapped. This happens to
            # match the field default in 1.5.0, but create_transport() sets it
            # explicitly on the auto path and so do we — it is load-bearing, not
            # something to leave to a default that could move.
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    # NOTE: passing language="en-IN" directly as a DeepgramSTTService kwarg is
    # a silent no-op on Pipecat 1.5.0 (it always resolves to Language.EN
    # regardless of the value given) — it must go through settings= instead.
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        settings=DeepgramSTTSettings(
            model="nova-3",
            language="en-IN",
            smart_format=True,
            interim_results=True,
            endpointing=300,
        ),
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        ),
    )

    # ElevenLabsHttpTTSService requires an aiohttp session that we create and
    # manage ourselves. It must stay open for as long as tts is in use — that's
    # the duration of this one call, so everything from here through
    # runner.run() lives inside this block.
    async with aiohttp.ClientSession() as session:
        tts = ElevenLabsHttpTTSService(
            api_key=os.getenv("ELEVENLABS_API_KEY"),
            aiohttp_session=session,
            # Pipecat derives the ElevenLabs output_format from sample_rate: at
            # 8000 that's pcm_8000, which is exactly what Exotel wants, so the
            # audio leaves ElevenLabs already in the carrier's format.
            sample_rate=EXOTEL_SAMPLE_RATE,
            settings=ElevenLabsHttpTTSSettings(
                model=os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2"),
                voice=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            ),
        )

        context = LLMContext(
            messages=[
                {
                    "role": "system",
                    "content": build_system_prompt(project_kb=project_kb),
                }
            ]
        )
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                # PipelineParams has no allow_interruptions field in Pipecat 1.5.0;
                # interruption is controlled by these user-turn start strategies.
                #
                # enable_interruptions=True makes the aggregator broadcast an
                # InterruptionFrame when a turn starts. That frame is a
                # SystemFrame, so it bypasses processor queues and actually
                # preempts work in flight rather than queueing behind it:
                #   - every processor resets its process task, flushing frames
                #     already queued (frame_processor._start_interruption)
                #   - TTSService clears its aggregator, frame sequencer and
                #     pending LLMFullResponseEnd frames
                #   - the output transport drains queued audio, so buffered
                #     speech is dropped instead of played out
                #   - the assistant aggregator calls reset() *without*
                #     push_aggregation(), so the interrupted reply is discarded
                #     rather than committed to the context
                # Both strategies are enabled: VAD is the fast path, and
                # transcription is the fallback for a caller too quiet to trip
                # VAD but still transcribed by Deepgram.
                user_turn_strategies=UserTurnStrategies(
                    start=[
                        VADUserTurnStartStrategy(enable_interruptions=True),
                        TranscriptionUserTurnStartStrategy(enable_interruptions=True),
                    ]
                ),
            ),
        )

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        # The Week 2 latency harness appends to a single fixed CSV, which two
        # concurrent calls would interleave into nonsense — so it's opt-in here
        # rather than always-on the way it was in test_pipeline.py.
        observers = []
        latency_csv = os.getenv("NXLYR_LATENCY_CSV")
        if latency_csv:
            from week2_latency_observer import make_week2_latency_observer

            observers.append(make_week2_latency_observer(latency_csv))

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=EXOTEL_SAMPLE_RATE,
                audio_out_sample_rate=EXOTEL_SAMPLE_RATE,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=observers,
        )

        @transport.event_handler("on_client_connected")
        async def on_client_connected(transport, client):
            # Bot speaks first. The official outbound example stays silent here,
            # but that's for its connect-two-numbers flow where the bot leg
            # answers before the customer is even dialed. Ours is a pre-sales
            # agent that should open the conversation.
            #
            # This used to queue an LLMRunFrame and let the LLM improvise an
            # opening line from the system prompt alone. That's what produced
            # Call #1's bug (00_PROJECT_CONTEXT.md): the model didn't greet
            # until 65 seconds in. Pushing GREETING as a TTSSpeakFrame instead
            # makes the opening line fixed and instant — no LLM round trip to
            # wait on turn 1. append_to_context defaults to True, so it's still
            # recorded as the first assistant turn for later turns to build on.
            logger.info(f"Client connected — sending greeting (call_sid={call_sid})")
            await worker.queue_frames([TTSSpeakFrame(GREETING)])

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info(f"Client disconnected (call_sid={call_sid})")
            await worker.cancel()

        # handle_sigint=False: signal handling belongs to the uvicorn process that
        # owns us, not to one call's pipeline.
        runner = WorkerRunner(handle_sigint=False)

        await runner.add_workers(worker)
        await runner.run()

    logger.info(f"Call finished (call_sid={call_sid})")
