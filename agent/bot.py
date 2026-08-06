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

import os
import sys

import aiohttp
from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import WebSocket

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame
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
            model="gpt-4o",
            max_tokens=160,
            temperature=0.75,
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
                    "content": (
                        "You are a friendly real estate pre-sales assistant for an "
                        "Indian property developer. Keep replies short (1-2 sentences) "
                        "and conversational, like a real phone call."
                    ),
                }
            ]
        )
        context_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                # PipelineParams has no allow_interruptions field in Pipecat 1.5.0;
                # interruption is controlled by these user-turn start strategies.
                user_turn_strategies=UserTurnStrategies(
                    start=[
                        VADUserTurnStartStrategy(enable_interruptions=False),
                        TranscriptionUserTurnStartStrategy(enable_interruptions=False),
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
            # agent that should open the conversation — same kickoff
            # test_pipeline.py used.
            logger.info(f"Client connected — starting conversation (call_sid={call_sid})")
            await worker.queue_frames([LLMRunFrame()])

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
