"""
NXLYR — local voice pipeline smoke test (Implementation Plan, Week 2 / Task 1.2)

Mic input -> Deepgram STT -> GPT-4o -> ElevenLabs TTS -> speaker output

Verified against Pipecat 1.5.0 import paths (see TRD Addendum A4 for the
Pipecat Flows note, and the Week 2 task correction that goes with it).

Requires environment variables (export them yourself, or create a .env
and uncomment the load_dotenv() call below once Task 1.5 is done):
  DEEPGRAM_API_KEY
  OPENAI_API_KEY
  ELEVENLABS_API_KEY
  ELEVENLABS_VOICE_ID   (optional — defaults to a stock ElevenLabs voice)
"""

import asyncio
import os
import sys

from loguru import logger

from dotenv import load_dotenv
load_dotenv(override=True)

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    LLMRunFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

REQUIRED_ENV_VARS = ["DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"]


# LOCAL-DEV-ONLY WORKAROUND — remove before Week 3 Exotel integration.
# Exotel's telephony stream won't have this echo problem (separate in/out legs),
# but on a local speaker+mic setup the mic picks up the bot's own TTS output and
# feeds it back into Deepgram as fake user speech. This processor sits right after
# transport.input() and drops mic audio frames while the bot is talking, using the
# BotStartedSpeakingFrame/BotStoppedSpeakingFrame frames that flow upstream from
# transport.output() to gate them.
class MicGateDevOnly(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.bot_speaking = False

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = False
            await self.push_frame(frame, direction)
            return

        if self.bot_speaking and isinstance(frame, InputAudioRawFrame):
            return

        await self.push_frame(frame, direction)


def check_env():
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)


async def main():
    check_env()

    # Note: vad_analyzer used to live here on TransportParams, but that's
    # deprecated as of recent Pipecat releases — VAD now attaches to the
    # context aggregator instead (see below).
    transport = LocalAudioTransport(
        LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        )
    )

    # NOTE: passing language="en-IN" directly as a DeepgramSTTService kwarg is
    # a silent no-op on Pipecat 1.5.0 (it always resolves to Language.EN
    # regardless of the value given) — it must go through settings= instead.
    stt = DeepgramSTTService(
        api_key=os.getenv("DEEPGRAM_API_KEY"),
        settings=DeepgramSTTSettings(language="en-IN"),
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        model="gpt-4o",
    )

    tts = ElevenLabsTTSService(
        api_key=os.getenv("ELEVENLABS_API_KEY"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
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
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            MicGateDevOnly(),  # local-dev-only workaround, see class comment above
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
            context_aggregator.assistant(),
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=False, enable_metrics=True),
    )

    runner = PipelineRunner()

    # Kick off the conversation so the bot greets you first.
    await task.queue_frame(LLMRunFrame())

    logger.info("Pipeline starting — speak into your mic. Ctrl+C to stop.")
    await runner.run(task)


if __name__ == "__main__":
    asyncio.run(main())
