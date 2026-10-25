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
  REDIS_URL             (optional, but wanted in production — without it the
                         tool handlers cannot write the session flags Flow 3's
                         drop detection reads, so every clean bot-initiated
                         hangup gets misfiled as a dropped call. The call
                         itself still runs.)
"""

import asyncio
import math
import os
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Mapping

import aiohttp
from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import WebSocket

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.services.deepgram.stt import DeepgramSTTSettings
# Switched from ElevenLabsTTSService (WebSocket) to ElevenLabsHttpTTSService (HTTP):
# on this Hetzner/Docker setup the websocket connection went unhealthy after the
# first turn with no error logged (matches known Pipecat websocket-reconnect
# issues), silently killing TTS for the rest of the run. HTTP is the Pipecat-docs
# recommended fallback for "when WebSocket connections are not possible" and our
# test has no interruption/word-timestamp needs that would require the websocket.
from pipecat.services.elevenlabs.tts import ElevenLabsHttpTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_start import (
    TranscriptionUserTurnStartStrategy,
    VADUserTurnStartStrategy,
)
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner
from pipecat.processors.frame_processor import FrameDirection

from convo_config import log_line, read_convo_config, tags_allowed
from log_scrub import configure_logging
from prompt import (
    AI_DISCLOSURE_MODE,
    COMPANY_DISPLAY,
    LEAD_SOURCE_DEMO_FORM,
    build_greeting,
    build_initial_messages,
)
from stt_keyterms import STTCheckingDeepgramService, build_keyterms
from tools import TOOL_SCHEMAS, CallResources, make_redis_client
from voice_config import log_line as voice_log_line, read_override, resolve, to_settings, tts_filters

# Bare logger.remove() rather than test_pipeline.py's logger.remove(0): this module
# is imported by a long-lived server, and remove(0) raises if the default handler
# is already gone.
logger.remove()
configure_logging(os.getenv("LOG_LEVEL"))

REQUIRED_ENV_VARS = ["DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"]

TURN_MODE_ENV_VAR = "NXLYR_TURN_MODE"
TURN_BACKSTOP_ENV_VAR = "NXLYR_TURN_BACKSTOP_SECS"
SMART_BACKSTOP_MODE = "smart_backstop"
SPEECH_TIMEOUT_MODE = "speech_timeout"
DEFAULT_TURN_BACKSTOP_SECS = 0.8
SPEECH_TIMEOUT_SECS = 0.6
SMART_TURN_GUARD_SECS = 0.2
MIN_TURN_BACKSTOP_SECS = 0.3
MAX_TURN_BACKSTOP_SECS = 2.0


class TurnReleaseConfigurationError(RuntimeError):
    """Raised at process startup when the turn-release environment is invalid."""


@dataclass(frozen=True)
class TurnReleaseConfig:
    mode: str
    backstop_secs: float


def load_turn_release_config(
    environment: Mapping[str, str] | None = None,
) -> TurnReleaseConfig:
    """Parse the immutable process-start turn-release configuration."""
    environment = environment if environment is not None else os.environ
    raw_mode = environment.get(TURN_MODE_ENV_VAR)
    mode = raw_mode or SMART_BACKSTOP_MODE
    if mode not in (SMART_BACKSTOP_MODE, SPEECH_TIMEOUT_MODE):
        raise TurnReleaseConfigurationError(
            f"{TURN_MODE_ENV_VAR}={raw_mode!r} must be one of "
            f"{SMART_BACKSTOP_MODE!r}, {SPEECH_TIMEOUT_MODE!r}"
        )

    raw_backstop = environment.get(TURN_BACKSTOP_ENV_VAR) or None
    if raw_backstop is None:
        backstop_secs = DEFAULT_TURN_BACKSTOP_SECS
    else:
        try:
            backstop_secs = float(raw_backstop)
        except ValueError as error:
            raise TurnReleaseConfigurationError(
                f"{TURN_BACKSTOP_ENV_VAR}={raw_backstop!r} must be a finite decimal "
                f"in the inclusive range {MIN_TURN_BACKSTOP_SECS} through "
                f"{MAX_TURN_BACKSTOP_SECS}"
            ) from error

    if not math.isfinite(backstop_secs) or not (
        MIN_TURN_BACKSTOP_SECS <= backstop_secs <= MAX_TURN_BACKSTOP_SECS
    ):
        raise TurnReleaseConfigurationError(
            f"{TURN_BACKSTOP_ENV_VAR}={raw_backstop!r} must be a finite decimal "
            f"in the inclusive range {MIN_TURN_BACKSTOP_SECS} through "
            f"{MAX_TURN_BACKSTOP_SECS}"
        )

    return TurnReleaseConfig(mode=mode, backstop_secs=backstop_secs)


# Read once during module/process initialization so a malformed image fails its
# import smoke and health check before a WebSocket can reach run_bot().
TURN_RELEASE_CONFIG = load_turn_release_config()
logger.info(
    f"turn release configured: mode={TURN_RELEASE_CONFIG.mode} "
    f"backstop_secs={TURN_RELEASE_CONFIG.backstop_secs}"
)


def build_user_turn_strategies(
    config: TurnReleaseConfig = TURN_RELEASE_CONFIG,
    *,
    turn_analyzer_factory: Callable[[SmartTurnParams], object] | None = None,
    smart_turn_guard_secs: float = SMART_TURN_GUARD_SECS,
) -> UserTurnStrategies:
    """Build the explicit start/stop strategy lists for one immutable config."""
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
    #   - the assistant aggregator commits the words already spoken with
    #     push_aggregation() before reset(), so partial speech remains in the
    #     context
    # Both strategies are enabled: VAD is the fast path, and
    # transcription is the fallback for a caller too quiet to trip
    # VAD but still transcribed by Deepgram.
    start = [
        VADUserTurnStartStrategy(enable_interruptions=True),
        TranscriptionUserTurnStartStrategy(enable_interruptions=True),
    ]

    if config.mode == SPEECH_TIMEOUT_MODE:
        return UserTurnStrategies(
            start=start,
            stop=[
                SpeechTimeoutUserTurnStopStrategy(
                    user_speech_timeout=SPEECH_TIMEOUT_SECS,
                    wait_for_transcript=True,
                )
            ],
        )

    smart_turn_stop_secs = config.backstop_secs + smart_turn_guard_secs
    if smart_turn_stop_secs < config.backstop_secs + SMART_TURN_GUARD_SECS:
        raise TurnReleaseConfigurationError(
            "smart_turn_stop_secs must be at least 0.2 seconds greater than "
            f"{TURN_BACKSTOP_ENV_VAR}"
        )

    make_analyzer = turn_analyzer_factory or (
        lambda params: LocalSmartTurnAnalyzerV3(params=params)
    )
    return UserTurnStrategies(
        start=start,
        stop=[
            TurnAnalyzerUserTurnStopStrategy(
                turn_analyzer=make_analyzer(SmartTurnParams(stop_secs=smart_turn_stop_secs)),
                wait_for_transcript=True,
            ),
            SpeechTimeoutUserTurnStopStrategy(
                user_speech_timeout=config.backstop_secs,
                wait_for_transcript=True,
            ),
        ],
    )


def _build_user_aggregator_params(
    user_turn_strategies: UserTurnStrategies | None = None,
) -> LLMUserAggregatorParams:
    """Keep the production VAD and turn-strategy wiring directly testable."""
    return LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(),
        user_turn_strategies=user_turn_strategies or build_user_turn_strategies(),
    )

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


def _call_timing(
    event: str,
    *,
    ws_connected_at: float | None,
    conn_id: str | None,
    **fields: int | str,
) -> None:
    if ws_connected_at is None or conn_id is None:
        return
    elapsed_ms = max(0, int((monotonic() - ws_connected_at) * 1000))
    extras = "".join(f" {key}={value}" for key, value in fields.items())
    logger.info(f"call timing: {event} conn={conn_id} t_ms={elapsed_ms}{extras}")


class CallTimingObserver(BaseObserver):
    """Log the first caller speech and first bot audio once per call."""

    def __init__(self, *, ws_connected_at: float, conn_id: str) -> None:
        super().__init__()
        self._ws_connected_at = ws_connected_at
        self._conn_id = conn_id
        self._caller_spoke = False
        self._greeting_audio_sent = False
        self._seen_frames: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        if data.direction != FrameDirection.DOWNSTREAM:
            return
        frame = data.frame
        if not isinstance(frame, (VADUserStartedSpeakingFrame, BotStartedSpeakingFrame)):
            return
        if frame.id in self._seen_frames:
            return
        self._seen_frames.add(frame.id)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            if not self._caller_spoke and not self._greeting_audio_sent:
                self._caller_spoke = True
                _call_timing(
                    "caller_spoke_before_greeting_audio",
                    ws_connected_at=self._ws_connected_at,
                    conn_id=self._conn_id,
                )
        elif not self._greeting_audio_sent:
            self._greeting_audio_sent = True
            _call_timing(
                "first_bot_audio_sent",
                ws_connected_at=self._ws_connected_at,
                conn_id=self._conn_id,
            )


async def run_bot(
    websocket: WebSocket,
    *,
    ws_connected_at: float | None = None,
    conn_id: str | None = None,
) -> None:
    """Run one call's pipeline to completion over an accepted Exotel WebSocket.

    server.py's /ws route accepts the socket and hands it here. Returns when the
    call ends; the caller is responsible for closing the socket.
    """
    run_bot_started_at = monotonic()
    check_env()
    logger.info(
        f"turn release call start: mode={TURN_RELEASE_CONFIG.mode} "
        f"backstop_secs={TURN_RELEASE_CONFIG.backstop_secs}"
    )

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
    from kb_loader import kb_cache_source

    kb_source = kb_cache_source(KB_PROJECT_SLUG)
    kb_started_at = monotonic()
    try:
        project_kb = await asyncio.to_thread(load_project_kb)
    except Exception as e:
        logger.error(
            f"Project KB failed to load for slug={KB_PROJECT_SLUG!r} "
            f"(call_sid={call_sid}) — aborting call: {e}"
        )
        raise
    kb_ms = max(0, int((monotonic() - kb_started_at) * 1000))

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
    convo_cfg = await read_convo_config()
    stt_settings = {
        "model": "nova-3",
        "language": "en-IN",
        "smart_format": True,
        "interim_results": True,
        "endpointing": 300,
    }
    if convo_cfg.stt_keyterms:
        stt_settings["keyterm"] = build_keyterms(project_kb)
    if convo_cfg.stt_numerals:
        stt_settings["numerals"] = True
    stt_args = {
        "api_key": os.getenv("DEEPGRAM_API_KEY"),
        "settings": DeepgramSTTSettings(**stt_settings),
        "conn_id": conn_id,
        "region": convo_cfg.stt_region,
        "project_name": project_kb.get("project_name"),
    }
    if convo_cfg.stt_region == "eu":
        stt_args["base_url"] = "api.eu.deepgram.com"
    stt = STTCheckingDeepgramService(
        **stt_args,
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
        voice_cfg = resolve(await read_override(), os.environ)
        logger.info(voice_log_line(voice_cfg, conn_id))
        tts = ElevenLabsHttpTTSService(
            api_key=os.getenv("ELEVENLABS_API_KEY"),
            aiohttp_session=session,
            # Pipecat derives the ElevenLabs output_format from sample_rate: at
            # 8000 that's pcm_8000, which is exactly what Exotel wants, so the
            # audio leaves ElevenLabs already in the carrier's format.
            sample_rate=EXOTEL_SAMPLE_RATE,
            settings=to_settings(voice_cfg),
            text_filters=tts_filters(voice_cfg),
        )

        # tools= goes on the LLMContext, not on OpenAILLMService — that service
        # has no tools parameter in Pipecat 1.5.0 (its __init__ takes only
        # model/service_tier/params/settings). Each schema in TOOL_SCHEMAS
        # carries its own handler, and LLMService._register_advertised_tool_
        # handlers() registers them automatically from the context, so there is
        # deliberately no register_function() call here.
        messages = build_initial_messages(
            project_kb,
            lead_source=LEAD_SOURCE_DEMO_FORM,
            version=convo_cfg.prompt_version,
        )
        plain_greeting = messages[-1]["content"]
        tts_model = voice_cfg.model
        greeting_tags_blocked = convo_cfg.greeting_tags and not tags_allowed(tts_model)
        if greeting_tags_blocked:
            logger.warning(
                "greeting_tags is on but the voice model is not v4; using the plain greeting"
            )
        greeting = (
            build_greeting(
                LEAD_SOURCE_DEMO_FORM,
                project_kb.get("project_name"),
                tags=True,
            )
            if convo_cfg.greeting_tags and not greeting_tags_blocked
            else plain_greeting
        )
        logger.info(
            f"prompt v2: chars={len(messages[0]['content'])} "
            f"lead_source={LEAD_SOURCE_DEMO_FORM} "
            f"disclosure_mode={AI_DISCLOSURE_MODE} company={COMPANY_DISPLAY} "
            f"version={convo_cfg.prompt_version}"
        )
        logger.info(
            log_line(
                convo_cfg,
                conn_id,
                greeting_tags_blocked=greeting_tags_blocked,
            )
        )
        context = LLMContext(messages=messages, tools=TOOL_SCHEMAS)
        models_started_at = monotonic()
        user_params = await asyncio.to_thread(_build_user_aggregator_params)
        models_ms = max(0, int((monotonic() - models_started_at) * 1000))
        _call_timing(
            "models_built",
            ws_connected_at=ws_connected_at,
            conn_id=conn_id,
            models_ms=models_ms,
        )
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=user_params,
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
        if ws_connected_at is not None and conn_id is not None:
            observers.append(
                CallTimingObserver(
                    ws_connected_at=ws_connected_at,
                    conn_id=conn_id,
                )
            )
        latency_csv = os.getenv("NXLYR_LATENCY_CSV")
        if latency_csv:
            from week2_latency_observer import make_week2_latency_observer

            observers.append(make_week2_latency_observer(latency_csv))

        # Per-call state for the tool handlers, reached via
        # FunctionCallParams.app_resources. app_resources is passed by
        # reference, so all three handlers share this one object for the
        # duration of the call — which is what lets them write the session
        # flags without a module-level global that two concurrent calls in the
        # same process would trample.
        #
        # make_redis_client() returns None instead of raising when REDIS_URL is
        # unset or the server is unreachable. Unlike the KB load above — which
        # aborts the call, because there is no conversation to have without a
        # KB — a missing Redis only degrades post-call drop classification, and
        # dropping a live buyer over an analytics write would be the worse bug.
        redis_started_at = monotonic()
        redis_client = await make_redis_client()
        redis_ms = max(0, int((monotonic() - redis_started_at) * 1000))
        call_resources = CallResources(call_sid=call_sid, redis=redis_client)

        _call_timing(
            "setup_done",
            ws_connected_at=ws_connected_at,
            conn_id=conn_id,
            kb_ms=kb_ms,
            kb_source=kb_source,
            redis_ms=redis_ms,
            handshake_ms=max(
                0,
                int(
                    (run_bot_started_at - ws_connected_at) * 1000
                    if ws_connected_at is not None
                    else 0
                ),
            ),
        )

        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=EXOTEL_SAMPLE_RATE,
                audio_out_sample_rate=EXOTEL_SAMPLE_RATE,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=observers,
            app_resources=call_resources,
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
            # until 65 seconds in. Pushing the greeting as a TTSSpeakFrame instead
            # makes the opening line fixed and instant — no LLM round trip to
            # wait on turn 1. It is already seeded into messages, so this frame
            # must not append it to the context a second time.
            logger.info(f"Client connected — sending greeting (call_sid={call_sid})")
            _call_timing(
                "greeting_queued",
                ws_connected_at=ws_connected_at,
                conn_id=conn_id,
            )
            await worker.queue_frames(
                [TTSSpeakFrame(greeting, append_to_context=False)]
            )

        @transport.event_handler("on_client_disconnected")
        async def on_client_disconnected(transport, client):
            logger.info(f"Client disconnected (call_sid={call_sid})")
            await worker.cancel()

        # handle_sigint=False: signal handling belongs to the uvicorn process that
        # owns us, not to one call's pipeline.
        runner = WorkerRunner(handle_sigint=False)

        try:
            await runner.add_workers(worker)
            await runner.run()
        finally:
            # try/finally rather than a plain call after run(): server.py's /ws
            # handler catches whatever escapes run_bot(), so without this a
            # failed call would leak the connection for the process lifetime.
            # The session hash itself is left in Redis on purpose — Flow 3's
            # post-call webhook is what reads end_call_tool_invoked, and it
            # fires after this coroutine is gone. The 4h EXPIRE that
            # tools._set_session_flag arms is what cleans it up.
            if redis_client is not None:
                await redis_client.aclose()

    logger.info(f"Call finished (call_sid={call_sid})")
