import asyncio
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pipecat.frames.frames import (
    AggregationType,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseStartFrame,
    OutputAudioRawFrame,
    TTSTextFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.turns.user_start import UserTurnStartedParams
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy
from pipecat.turns.user_turn_controller import UserTurnController
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.asyncio.task_manager import TaskManager


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import bargein
import log_scrub

with patch("dotenv.load_dotenv"):
    import bot


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self._waiters: list[tuple[float, asyncio.Future[None]]] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self._waiters.append((self.now + delay, future))
        await future

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for deadline, future in list(self._waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)


class BargeInClassifierTests(unittest.TestCase):
    def test_a1_frozen_lists_include_every_founder_phrase(self) -> None:
        expected_stops = {
            "wait", "stop", "hold on", "ruko", "ek minute", "nahi", "no",
            "actually", "sorry", "excuse me", "sunno", "रुको", "एक मिनट",
            "नहीं", "सुनो", "रुकिए",
        }
        expected_agreements = {
            "haan", "haanji", "ha", "accha", "theek hai", "thik hai", "hmm",
            "mm-hmm", "ok", "okay", "yes", "ji", "right", "sure", "हाँ",
            "हां", "हाँ जी", "जी", "अच्छा", "ठीक है", "हम्म", "ओके",
            "theek", "thik",
            "yeah", "yep", "uh-huh", "mhm", "mmhmm", "han", "haan ji",
        }
        self.assertTrue(expected_stops.issubset(set(bargein.STOP_PHRASES)))
        self.assertTrue(expected_agreements.issubset(set(bargein.AGREEMENT_PHRASES)))

    def test_a1_devanagari_punctuation_matches_ascii_punctuation(self) -> None:
        for phrase in bargein.STOP_PHRASES:
            expected = bargein.classify(f"{phrase}.")
            for punctuation in ("।", "॥"):
                with self.subTest(kind="stop", phrase=phrase, punctuation=punctuation):
                    self.assertEqual(bargein.classify(f"{phrase}{punctuation}"), expected)
        for phrase in bargein.AGREEMENT_PHRASES:
            expected = bargein.classify(f"{phrase}.")
            for punctuation in ("।", "॥"):
                with self.subTest(kind="agreement", phrase=phrase, punctuation=punctuation):
                    self.assertEqual(bargein.classify(f"{phrase}{punctuation}"), expected)

        self.assertEqual(bargein.classify("ठीक है।"), bargein.BargeInKind.IGNORE)
        self.assertEqual(bargein.classify("हाँ।"), bargein.BargeInKind.IGNORE)

    def test_a1_backchannel_variants_normalize_without_overmatching_boundaries(self) -> None:
        agreements = (
            "yeah", "yep", "uh-huh", "mhm", "mmhmm", "han", "haan ji",
            "hmm", "hmmm", "hmmmm", "accha", "acha", "achha", "achcha",
            "हम्म", "हम्म्म", "हम्म्म्म", "हाँ", "हां", "अच्छा", "अछा", "अच्चा", "हां जी",
        )
        for phrase in agreements:
            for punctuation in (".", "।", "॥"):
                with self.subTest(phrase=phrase, punctuation=punctuation):
                    self.assertEqual(
                        bargein.classify(f"{phrase}{punctuation}"),
                        bargein.BargeInKind.IGNORE,
                    )
        for text in ("okayness", "rightmove", "नहींजी"):
            with self.subTest(boundary=text):
                self.assertNotEqual(bargein.classify(text), bargein.BargeInKind.IGNORE)

    def test_a1_classifier_table(self) -> None:
        for phrase in bargein.STOP_PHRASES:
            for rendered in (phrase, f"...{phrase.upper()}?!"):
                with self.subTest(kind="stop", phrase=rendered):
                    self.assertEqual(
                        bargein.classify(rendered), bargein.BargeInKind.INTERRUPT
                    )

        agreements = list(bargein.AGREEMENT_PHRASES) + [
            "haan haan ji",
            "accha theek hai",
            "हाँ, हाँ जी!",
        ]
        for phrase in agreements:
            for rendered in (phrase, f"...{phrase.upper()}?!"):
                with self.subTest(kind="agreement", phrase=rendered):
                    self.assertEqual(
                        bargein.classify(rendered), bargein.BargeInKind.IGNORE
                    )

        cases = {
            "what is the price": bargein.BargeInKind.INTERRUPT,
            "price": bargein.BargeInKind.LONE_WORD,
            "": bargein.BargeInKind.NO_WORDS,
            "theek": bargein.BargeInKind.IGNORE,
            "haan price": bargein.BargeInKind.LONE_WORD,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(bargein.classify(text), expected)


class SmartBargeInStrategyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = FakeClock()
        self.real_sleep = asyncio.sleep

    async def _controller(self, *, greeting_done: bool = True):
        trace = bargein.BargeInTrace(
            mode="smart", conn_id="abcdef", clock=self.clock
        )
        strategy = bargein.SmartBargeInStartStrategy(
            trace=trace,
            clock=self.clock,
            sleep=self.clock.sleep,
        )
        controller = UserTurnController(
            user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[]),
            user_turn_stop_timeout=30.0,
        )
        starts = []
        stops = []
        resets = []

        @controller.event_handler("on_user_turn_started")
        async def on_started(_, active_strategy, params) -> None:
            starts.append((active_strategy, params))

        @controller.event_handler("on_user_turn_stopped")
        async def on_stopped(_, active_strategy, params) -> None:
            stops.append((active_strategy, params))

        @controller.event_handler("on_reset_aggregation")
        async def on_reset(_, active_strategy) -> None:
            resets.append(active_strategy)

        await controller.setup(TaskManager())
        self.addAsyncCleanup(controller.cleanup)
        await controller.process_frame(BotStartedSpeakingFrame())
        if greeting_done:
            await controller.process_frame(BotStoppedSpeakingFrame())
            await controller.process_frame(BotStartedSpeakingFrame())
        return controller, strategy, trace, starts, stops, resets

    async def _drain(self) -> None:
        await self.real_sleep(0)

    async def test_a2_vad_and_backchannels_do_not_start_a_turn(self) -> None:
        controller, _, _, starts, stops, resets = await self._controller()
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        self.assertEqual(starts, [])
        await controller.process_frame(
            TranscriptionFrame("haan", "user", "0", finalized=True)
        )
        self.assertEqual(starts, [])
        self.assertEqual(len(resets), 1)
        await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
        self.assertEqual(stops, [])

        controller, _, _, starts, _, resets = await self._controller()
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        await controller.process_frame(
            TranscriptionFrame("accha theek hai", "user", "0", finalized=True)
        )
        self.assertEqual(starts, [])
        self.assertEqual(len(resets), 1)

    async def test_a2_stop_words_multi_word_and_final_lone_word_interrupt(self) -> None:
        cases = (
            InterimTranscriptionFrame("wait", "user", "0"),
            InterimTranscriptionFrame("ruko", "user", "0"),
            InterimTranscriptionFrame("what is the price", "user", "0"),
            TranscriptionFrame("price", "user", "0", finalized=True),
        )
        for transcript in cases:
            with self.subTest(transcript=transcript.text):
                controller, _, _, starts, _, _ = await self._controller()
                await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
                await controller.process_frame(transcript)
                self.assertEqual(len(starts), 1)
                self.assertTrue(starts[0][1].enable_interruptions)

    async def test_a2_sustained_speech_fires_at_point_eight_five_only_for_real_word(self) -> None:
        controller, _, _, starts, _, _ = await self._controller()
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        await controller.process_frame(InterimTranscriptionFrame("price", "user", "0"))
        await self._drain()
        self.clock.advance(0.84)
        await self._drain()
        self.assertEqual(starts, [])
        self.clock.advance(0.01)
        await self._drain()
        self.assertEqual(len(starts), 1)

        controller, _, _, starts, _, _ = await self._controller()
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        await controller.process_frame(InterimTranscriptionFrame("haan", "user", "0"))
        self.clock.advance(1.0)
        await self._drain()
        self.assertEqual(starts, [])

    async def test_a2_not_speaking_matches_legacy_and_end_edge_is_not_filtered(self) -> None:
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef", clock=self.clock)
        strategy = bargein.SmartBargeInStartStrategy(trace=trace, clock=self.clock)
        controller = UserTurnController(
            user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[]),
            user_turn_stop_timeout=30.0,
        )
        starts = []

        @controller.event_handler("on_user_turn_started")
        async def on_started(_, active_strategy, params) -> None:
            starts.append((active_strategy, params))

        await controller.setup(TaskManager())
        self.addAsyncCleanup(controller.cleanup)
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        self.assertEqual(len(starts), 1)

        controller, _, _, starts, _, _ = await self._controller()
        await controller.process_frame(BotStoppedSpeakingFrame())
        await controller.process_frame(
            TranscriptionFrame("haan", "user", "0", finalized=True)
        )
        self.assertEqual(len(starts), 1)

        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef", clock=self.clock)
        strategy = bargein.SmartBargeInStartStrategy(trace=trace, clock=self.clock)
        controller = UserTurnController(
            user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[]),
            user_turn_stop_timeout=30.0,
        )
        starts = []

        @controller.event_handler("on_user_turn_started")
        async def on_transcript_started(_, active_strategy, params) -> None:
            starts.append((active_strategy, params))

        await controller.setup(TaskManager())
        self.addAsyncCleanup(controller.cleanup)
        await controller.process_frame(
            InterimTranscriptionFrame("", "user", "0")
        )
        self.assertEqual(len(starts), 1)

    async def test_a2_greeting_protection_blocks_lone_and_sustained_but_not_wait(self) -> None:
        controller, _, _, starts, _, resets = await self._controller(greeting_done=False)
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        await controller.process_frame(
            TranscriptionFrame("hello", "user", "0", finalized=True)
        )
        self.clock.advance(1.0)
        await self._drain()
        self.assertEqual(starts, [])
        self.assertEqual(len(resets), 1)

        controller, _, _, starts, _, _ = await self._controller(greeting_done=False)
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        await controller.process_frame(InterimTranscriptionFrame("wait", "user", "0"))
        self.assertEqual(len(starts), 1)

    async def test_a2_uh_huh_interim_and_devanagari_agreement_never_interrupt(self) -> None:
        for text in ("uh-huh", "ठीक है।", "हाँ।"):
            with self.subTest(text=text):
                controller, _, _, starts, _, _ = await self._controller()
                await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
                await controller.process_frame(InterimTranscriptionFrame(text, "user", "0"))
                self.clock.advance(1.0)
                await self._drain()
                self.assertEqual(starts, [])

    async def test_greeting_lone_real_word_is_delivered_after_greeting(self) -> None:
        context = LLMContext(messages=[])
        strategy = bargein.SmartBargeInStartStrategy(
            trace=bargein.BargeInTrace(mode="smart", conn_id="abcdef")
        )
        pair = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[])
            ),
        )
        await run_test(
            pair.user(),
            frames_to_send=[
                BotStartedSpeakingFrame(),
                VADUserStartedSpeakingFrame(start_secs=0.2),
                TranscriptionFrame("price", "user", "0", finalized=True),
                BotStoppedSpeakingFrame(),
            ],
        )
        self.assertEqual(context.get_messages(), [{"role": "user", "content": "price"}])

    async def test_slow_transcript_logs_counter_only_without_interrupting(self) -> None:
        controller, _, _, starts, _, _ = await self._controller()
        with patch.object(bargein.logger, "info") as info:
            await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
            await self._drain()
            self.clock.advance(1.49)
            await self._drain()
            self.assertEqual(info.call_args_list, [])
            self.clock.advance(0.01)
            await self._drain()
        self.assertEqual(starts, [])
        info.assert_called_once_with(
            "barge-in no-transcript: conn=abcdef count=1 t_vad_ms=1500"
        )

    async def test_a5_ignored_log_never_contains_transcript_words(self) -> None:
        controller, _, _, _, _, _ = await self._controller()
        with patch.object(bargein.logger, "info") as info:
            await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
            await controller.process_frame(
                InterimTranscriptionFrame("haan ji 9876543210", "user", "0")
            )
            await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
            await controller.process_frame(BotStoppedSpeakingFrame())
        rendered = " ".join(str(call.args[0]) for call in info.call_args_list)
        self.assertIn(
            "barge-in ignored: conn=abcdef kind=single_word_pending words=3",
            rendered,
        )
        self.assertNotIn("haan", rendered)
        self.assertNotIn("9876543210", rendered)

    async def test_a5_real_interruption_does_not_also_log_an_ignored_burst(self) -> None:
        controller, _, _, _, _, _ = await self._controller()
        with patch.object(bargein.logger, "info") as info:
            await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
            await controller.process_frame(InterimTranscriptionFrame("wait", "user", "0"))
            await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
        self.assertFalse(
            any("barge-in ignored:" in str(call.args[0]) for call in info.call_args_list)
        )

    async def test_a5_final_after_vad_stop_logs_the_burst_once_as_agreement(self) -> None:
        controller, _, _, _, _, _ = await self._controller()
        with patch.object(bargein.logger, "info") as info:
            await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
            await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
            await controller.process_frame(
                TranscriptionFrame("haan", "user", "0", finalized=True)
            )
            await controller.process_frame(BotStoppedSpeakingFrame())
        lines = [str(call.args[0]) for call in info.call_args_list]
        self.assertEqual(
            lines,
            ["barge-in ignored: conn=abcdef kind=agreement words=1"],
        )


class AggregatorBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a3_agreement_wipes_real_user_aggregator_without_llm_run(self) -> None:
        strategy = bargein.SmartBargeInStartStrategy(
            trace=bargein.BargeInTrace(mode="smart", conn_id="abcdef")
        )
        context = LLMContext(messages=[])
        pair = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[])
            ),
        )
        down, _ = await run_test(
            pair.user(),
            frames_to_send=[
                BotStartedSpeakingFrame(),
                BotStoppedSpeakingFrame(),
                BotStartedSpeakingFrame(),
                VADUserStartedSpeakingFrame(start_secs=0.2),
                TranscriptionFrame("haan", "user", "0", finalized=True),
                VADUserStoppedSpeakingFrame(stop_secs=0.2),
            ],
        )
        self.assertEqual(context.get_messages(), [])
        self.assertFalse(any(isinstance(frame, LLMContextFrame) for frame in down))

    async def test_punctuation_only_final_never_prefixes_the_next_turn(self) -> None:
        for punctuation in ("...", "।"):
            with self.subTest(punctuation=punctuation):
                strategy = bargein.SmartBargeInStartStrategy(
                    trace=bargein.BargeInTrace(mode="smart", conn_id="abcdef")
                )
                context = LLMContext(messages=[])
                pair = LLMContextAggregatorPair(
                    context,
                    user_params=LLMUserAggregatorParams(
                        user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[])
                    ),
                )
                await run_test(
                    pair.user(),
                    frames_to_send=[
                        BotStartedSpeakingFrame(),
                        BotStoppedSpeakingFrame(),
                        BotStartedSpeakingFrame(),
                        TranscriptionFrame(punctuation, "user", "0", finalized=True),
                        TranscriptionFrame("price please", "user", "1", finalized=True),
                    ],
                )
                self.assertEqual(
                    context.get_messages(), [{"role": "user", "content": "price please"}]
                )

    async def test_a8_interruption_commits_assistant_text_already_pushed(self) -> None:
        context = LLMContext(messages=[])
        assistant = LLMContextAggregatorPair(context).assistant()
        await run_test(
            assistant,
            frames_to_send=[
                LLMFullResponseStartFrame(),
                TTSTextFrame(
                    "Sentence one. Sentence two is long.",
                    aggregated_by=AggregationType.SENTENCE,
                ),
                InterruptionFrame(),
            ],
        )
        self.assertEqual(
            context.get_messages(),
            [{"role": "assistant", "content": "Sentence one. Sentence two is long."}],
        )

    async def test_a8_interruption_without_assistant_text_commits_nothing(self) -> None:
        context = LLMContext(messages=[])
        assistant = LLMContextAggregatorPair(context).assistant()
        await run_test(
            assistant,
            frames_to_send=[LLMFullResponseStartFrame(), InterruptionFrame()],
        )
        self.assertEqual(context.get_messages(), [])


class SerializerAndObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_aggregator_logs_once_per_interruption_and_not_silent_turn(self) -> None:
        class OutputProcessor(FrameProcessor):
            def __init__(self, serializer=None) -> None:
                super().__init__()
                self._serializer = serializer

            async def process_frame(self, frame, direction) -> None:
                await super().process_frame(frame, direction)
                if (
                    self._serializer
                    and direction == FrameDirection.DOWNSTREAM
                    and isinstance(frame, InterruptionFrame)
                ):
                    await asyncio.sleep(0)
                    await self._serializer.serialize(frame)
                await self.push_frame(frame, direction)

        async def run_scenario(mode, frames):
            with self.subTest(mode=mode):
                trace = bargein.BargeInTrace(mode=mode, conn_id="abcdef")
                start = (
                    [bargein.SmartBargeInStartStrategy(trace=trace)]
                    if mode == "smart"
                    else [
                        bot.VADUserTurnStartStrategy(enable_interruptions=True),
                        bot.TranscriptionUserTurnStartStrategy(enable_interruptions=True),
                    ]
                )
                pair = LLMContextAggregatorPair(
                    LLMContext(messages=[]),
                    user_params=LLMUserAggregatorParams(
                        user_turn_strategies=UserTurnStrategies(
                            start=start,
                            stop=[ExternalUserTurnStopStrategy(wait_for_transcript=False)],
                        )
                    ),
                )
                user = pair.user()
                serializer = (
                    bargein.DualKeyExotelSerializer(
                        stream_sid="stream-1", call_sid="call-1", trace=trace
                    )
                    if mode == "smart"
                    else None
                )
                output = OutputProcessor(serializer)
                observer = bargein.BargeInObserver(
                    trace=trace, user_aggregator=user, output_processor=output
                )
                with patch.object(bargein.logger, "info") as info:
                    await run_test(
                        Pipeline([user, output]),
                        frames_to_send=frames,
                        observers=[observer],
                    )
                return [
                    str(call.args[0])
                    for call in info.call_args_list
                    if str(call.args[0]).startswith("barge-in:")
                ]

        for mode in ("smart", "legacy"):
            with self.subTest(mode=mode):
                interruption_frames = []
                for burst in range(2):
                    interruption_frames.extend(
                        [
                            BotStartedSpeakingFrame(),
                            VADUserStartedSpeakingFrame(start_secs=0.2),
                        ]
                    )
                    if mode == "smart":
                        interruption_frames.append(InterimTranscriptionFrame("wait", "user", str(burst)))
                    interruption_frames.append(SleepFrame(0.01))
                    if mode == "legacy" and burst == 0:
                        interruption_frames.extend(
                            [
                                VADUserStoppedSpeakingFrame(stop_secs=0.2),
                                VADUserStartedSpeakingFrame(start_secs=0.2),
                                VADUserStoppedSpeakingFrame(stop_secs=0.2),
                            ]
                        )
                    interruption_frames.extend([UserStoppedSpeakingFrame(), SleepFrame(0.01)])

                lines = await run_scenario(mode, interruption_frames)
                self.assertEqual(len(lines), 2)
                self.assertTrue(all(f"mode={mode}" in line for line in lines))

                silent_frames = []
                for _ in range(3):
                    silent_frames.extend(
                        [
                            VADUserStartedSpeakingFrame(start_secs=0.2),
                            SleepFrame(0.01),
                            UserStoppedSpeakingFrame(),
                            SleepFrame(0.01),
                        ]
                    )
                self.assertEqual(await run_scenario(mode, silent_frames), [])

    async def test_a4_dual_key_serializer_matches_parent_payload_and_stamps_clear(self) -> None:
        clock = FakeClock()
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef", clock=clock)
        serializer = bargein.DualKeyExotelSerializer(
            stream_sid="stream-1", call_sid="call-1", trace=trace
        )
        parent = ExotelFrameSerializer(stream_sid="stream-1", call_sid="call-1")

        clock.advance(1.0)
        trace.note_bot_started()
        trace.stamp_fire()
        first_fire_at = trace.fire_at
        clock.advance(0.1)
        trace.stamp_fire()
        self.assertEqual(trace.fire_at, first_fire_at)
        clear = json.loads(await serializer.serialize(InterruptionFrame()))
        self.assertEqual(
            clear,
            {"event": "clear", "stream_sid": "stream-1", "streamSid": "stream-1"},
        )
        self.assertEqual(trace.clear_at, 1.1)

        audio = OutputAudioRawFrame(b"\x01\x02" * 160, sample_rate=8000, num_channels=1)
        dual_audio = json.loads(await serializer.serialize(audio))
        parent_audio = json.loads(await parent.serialize(audio))
        self.assertEqual(dual_audio["streamSid"], "stream-1")
        self.assertEqual(dual_audio["stream_sid"], "stream-1")
        self.assertEqual(dual_audio["media"]["payload"], parent_audio["media"]["payload"])
        self.assertIsNone(await serializer.serialize(BotStartedSpeakingFrame()))

    async def test_smart_playback_tail_stays_in_smart_path(self) -> None:
        clock = FakeClock()
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef", clock=clock)
        serializer = bargein.DualKeyExotelSerializer(
            stream_sid="stream-1", call_sid="call-1", trace=trace
        )
        strategy = bargein.SmartBargeInStartStrategy(
            trace=trace, clock=clock, sleep=clock.sleep
        )
        controller = UserTurnController(
            user_turn_strategies=UserTurnStrategies(start=[strategy], stop=[]),
            user_turn_stop_timeout=30.0,
        )
        starts = []

        @controller.event_handler("on_user_turn_started")
        async def on_started(_, active_strategy, params) -> None:
            starts.append((active_strategy, params))

        await controller.setup(TaskManager())
        self.addAsyncCleanup(controller.cleanup)
        await controller.process_frame(BotStartedSpeakingFrame())
        await serializer.serialize(
            OutputAudioRawFrame(b"\x01\x02" * 8000, sample_rate=8000, num_channels=1)
        )
        clock.advance(0.1)
        await controller.process_frame(BotStoppedSpeakingFrame())
        clock.advance(0.4)
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        self.assertEqual(starts, [])
        await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))

        clock.advance(0.6)
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.2))
        self.assertEqual(len(starts), 1)

    async def test_a5_observer_logs_ordered_offsets_and_no_transcript(self) -> None:
        clock = FakeClock()
        user = object()
        output = object()
        trace = bargein.BargeInTrace(mode="legacy", conn_id="abcdef", clock=clock)
        observer = bargein.BargeInObserver(
            trace=trace, user_aggregator=user, output_processor=output
        )
        vad = VADUserStartedSpeakingFrame(start_secs=0.2)
        interruption = InterruptionFrame()
        with patch.object(bargein.logger, "info") as info:
            await observer.on_push_frame(
                FramePushed(object(), object(), BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM, 0)
            )
            await observer.on_push_frame(
                FramePushed(object(), user, vad, FrameDirection.DOWNSTREAM, 0)
            )
            clock.advance(0.2)
            await observer.on_push_frame(
                FramePushed(user, object(), interruption, FrameDirection.DOWNSTREAM, 0)
            )
            clock.advance(0.05)
            await observer.on_push_frame(
                FramePushed(output, object(), interruption, FrameDirection.DOWNSTREAM, 0)
            )

        info.assert_called_once_with(
            "barge-in: conn=abcdef mode=legacy cause=legacy_vad "
            "t_vad_ms=0 t_fire_ms=200 t_clear_ms=250"
        )
        line = info.call_args.args[0]
        self.assertNotRegex(line, r"haan|wait|9876543210")

    async def test_each_interruption_has_fresh_timestamps_in_both_modes(self) -> None:
        for mode, burst_count in (("smart", 2), ("legacy", 3)):
            with self.subTest(mode=mode):
                clock = FakeClock()
                user = object()
                output = object()
                trace = bargein.BargeInTrace(mode=mode, conn_id="abcdef", clock=clock)
                observer = bargein.BargeInObserver(
                    trace=trace, user_aggregator=user, output_processor=output
                )
                serializer = bargein.DualKeyExotelSerializer(
                    stream_sid="stream-1", call_sid="call-1", trace=trace
                )
                with patch.object(bargein.logger, "info") as info:
                    await observer.on_push_frame(FramePushed(object(), object(), BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM, 0))
                    for index in range(burst_count):
                        await observer.on_push_frame(FramePushed(object(), user, VADUserStartedSpeakingFrame(start_secs=0.2), FrameDirection.DOWNSTREAM, 0))
                        clock.advance(0.1 + index * 0.01)
                        trace.arm("stop_word")
                        interruption = InterruptionFrame()
                        await observer.on_push_frame(FramePushed(user, object(), interruption, FrameDirection.DOWNSTREAM, 0))
                        clock.advance(0.02)
                        if mode == "smart":
                            await serializer.serialize(interruption)
                        else:
                            await observer.on_push_frame(FramePushed(output, object(), interruption, FrameDirection.DOWNSTREAM, 0))
                        await observer.on_push_frame(FramePushed(object(), object(), BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM, 0))
                lines = [str(call.args[0]) for call in info.call_args_list]
                self.assertEqual(len(lines), burst_count)
                for index, line in enumerate(lines):
                    self.assertIn(f"t_fire_ms={100 + index * 10}", line)
                    self.assertIn(f"t_clear_ms={120 + index * 10}", line)

    async def test_pause_and_resume_uses_the_latest_vad_timestamp(self) -> None:
        clock = FakeClock()
        user = object()
        output = object()
        trace = bargein.BargeInTrace(mode="legacy", conn_id="abcdef", clock=clock)
        observer = bargein.BargeInObserver(
            trace=trace, user_aggregator=user, output_processor=output
        )
        await observer.on_push_frame(FramePushed(object(), object(), BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM, 0))
        await observer.on_push_frame(FramePushed(object(), user, VADUserStartedSpeakingFrame(start_secs=0.2), FrameDirection.DOWNSTREAM, 0))
        await observer.on_push_frame(FramePushed(object(), user, VADUserStoppedSpeakingFrame(stop_secs=0.2), FrameDirection.DOWNSTREAM, 0))
        clock.advance(1.5)
        await observer.on_push_frame(FramePushed(object(), user, VADUserStartedSpeakingFrame(start_secs=0.2), FrameDirection.DOWNSTREAM, 0))
        clock.advance(0.1)
        interruption = InterruptionFrame()
        with patch.object(bargein.logger, "info") as info:
            await observer.on_push_frame(FramePushed(user, object(), interruption, FrameDirection.DOWNSTREAM, 0))
            clock.advance(0.02)
            await observer.on_push_frame(FramePushed(output, object(), interruption, FrameDirection.DOWNSTREAM, 0))
        self.assertIn("t_fire_ms=100 t_clear_ms=120", info.call_args.args[0])

    async def test_playback_end_uses_later_of_audio_duration_and_last_send(self) -> None:
        clock = FakeClock()
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef", clock=clock)
        serializer = bargein.DualKeyExotelSerializer(
            stream_sid="stream-1", call_sid="call-1", trace=trace
        )
        trace.note_bot_started()
        frame = OutputAudioRawFrame(b"\x01\x02" * 160, sample_rate=8000, num_channels=1)
        await serializer.serialize(frame)
        self.assertAlmostEqual(trace.playback_end_at(), 0.02)
        clock.advance(0.5)
        await serializer.serialize(frame)
        self.assertAlmostEqual(trace.playback_end_at(), 0.5)
        trace.stamp_fire()
        self.assertIsNone(trace.playback_end_at())

    async def test_ordinary_turn_start_while_bot_silent_logs_nothing_in_both_modes(self) -> None:
        for mode in ("smart", "legacy"):
            with self.subTest(mode=mode):
                user = object()
                output = object()
                trace = bargein.BargeInTrace(mode=mode, conn_id="abcdef")
                observer = bargein.BargeInObserver(
                    trace=trace, user_aggregator=user, output_processor=output
                )
                serializer = bargein.DualKeyExotelSerializer(
                    stream_sid="stream-1", call_sid="call-1", trace=trace
                )
                interruption = InterruptionFrame()
                with patch.object(bargein.logger, "info") as info:
                    await observer.on_push_frame(FramePushed(object(), user, VADUserStartedSpeakingFrame(start_secs=0.2), FrameDirection.DOWNSTREAM, 0))
                    await observer.on_push_frame(FramePushed(user, object(), interruption, FrameDirection.DOWNSTREAM, 0))
                    if mode == "smart":
                        await serializer.serialize(interruption)
                    else:
                        await observer.on_push_frame(FramePushed(output, object(), interruption, FrameDirection.DOWNSTREAM, 0))
                    info.assert_not_called()

                    await observer.on_push_frame(FramePushed(object(), object(), BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM, 0))
                    transcript_only = InterruptionFrame()
                    trace.arm("transcript")
                    await observer.on_push_frame(FramePushed(user, object(), transcript_only, FrameDirection.DOWNSTREAM, 0))
                    if mode == "smart":
                        await serializer.serialize(transcript_only)
                    else:
                        await observer.on_push_frame(FramePushed(output, object(), transcript_only, FrameDirection.DOWNSTREAM, 0))
                info.assert_called_once()
                self.assertIn("cause=transcript t_vad_ms=-", info.call_args.args[0])

    async def test_bargein_lines_pass_through_real_scrubbing_sink_without_words(self) -> None:
        output = io.StringIO()
        log_scrub.configure_logging("INFO", stream=output)
        try:
            trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef")
            trace.note_bot_started()
            trace.start_vad()
            trace.arm("stop_word")
            trace.stamp_fire()
            trace.stamp_clear_and_log()
            trace.log_ignored("agreement", 2)
            trace.log_no_transcript(trace.clock() - 1.5)
        finally:
            log_scrub.configure_logging("DEBUG")
        rendered = output.getvalue()
        self.assertIn("barge-in: conn=abcdef mode=smart cause=stop_word", rendered)
        self.assertIn("barge-in ignored: conn=abcdef kind=agreement words=2", rendered)
        self.assertIn(
            "barge-in no-transcript: conn=abcdef count=1 t_vad_ms=1500",
            rendered,
        )
        self.assertNotRegex(rendered, r"haan|wait|9876543210")


class LegacyParityTests(unittest.TestCase):
    def test_a7_unset_and_legacy_keep_strategies_vad_serializer_and_stops(self) -> None:
        default = bot.build_user_turn_strategies(
            turn_analyzer_factory=lambda params: object()
        )
        legacy = bot.build_user_turn_strategies(
            bargein_mode="legacy", turn_analyzer_factory=lambda params: object()
        )
        expected_start = [bot.VADUserTurnStartStrategy, bot.TranscriptionUserTurnStartStrategy]
        self.assertEqual([type(item) for item in default.start], expected_start)
        self.assertEqual([type(item) for item in legacy.start], expected_start)
        self.assertTrue(all(item._enable_interruptions for item in legacy.start))
        self.assertEqual([type(item) for item in default.stop], [type(item) for item in legacy.stop])

        sentinel = object()
        with patch.object(bot, "SileroVADAnalyzer", return_value=sentinel) as vad:
            params = bot._build_user_aggregator_params(
                legacy, bargein_mode="legacy"
            )
        vad.assert_called_once_with()
        self.assertIs(params.vad_analyzer, sentinel)

        with patch.object(bot, "DualKeyExotelSerializer") as dual:
            serializer = bot._build_exotel_serializer(
                stream_sid="stream-1",
                call_sid="call-1",
                bargein_mode="legacy",
                trace=bargein.BargeInTrace(mode="legacy", conn_id="abcdef"),
            )
        self.assertIs(type(serializer), ExotelFrameSerializer)
        self.assertEqual(serializer._stream_sid, "stream-1")
        self.assertEqual(serializer._call_sid, "call-1")
        params = serializer._params
        self.assertEqual(params.exotel_sample_rate, 8000)
        self.assertIsNone(params.sample_rate)
        dual.assert_not_called()

    def test_a7_smart_uses_one_strategy_and_tighter_vad(self) -> None:
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef")
        strategies = bot.build_user_turn_strategies(
            bargein_mode="smart",
            trace=trace,
            turn_analyzer_factory=lambda params: object(),
        )
        self.assertEqual([type(item) for item in strategies.start], [bargein.SmartBargeInStartStrategy])
        self.assertTrue(strategies.start[0]._enable_interruptions)

        sentinel = object()
        with patch.object(bot, "SileroVADAnalyzer", return_value=sentinel) as vad:
            params = bot._build_user_aggregator_params(
                strategies, bargein_mode="smart", trace=trace
            )
        vad.assert_called_once_with(params=bargein.SMART_VAD_PARAMS)
        self.assertIs(params.vad_analyzer, sentinel)

    def test_a7_call_context_reaches_zero_argument_thread_builder(self) -> None:
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef")
        strategies = object()
        token = bot._BARGEIN_BUILD_CONTEXT.set(("smart", trace))
        try:
            with patch.object(
                bot, "SileroVADAnalyzer", return_value=object()
            ) as vad, patch.object(
                bot, "build_user_turn_strategies", return_value=strategies
            ) as build:
                params = bot._build_user_aggregator_params()
        finally:
            bot._BARGEIN_BUILD_CONTEXT.reset(token)
        vad.assert_called_once_with(params=bargein.SMART_VAD_PARAMS)
        build.assert_called_once_with(bargein_mode="smart", trace=trace)
        self.assertIs(params.user_turn_strategies, strategies)


class AsyncWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_a7_context_reaches_builder_through_real_to_thread(self) -> None:
        trace = bargein.BargeInTrace(mode="smart", conn_id="abcdef")
        strategies = object()
        token = bot._BARGEIN_BUILD_CONTEXT.set(("smart", trace))
        try:
            with patch.object(
                bot, "SileroVADAnalyzer", return_value=object()
            ) as vad, patch.object(
                bot, "build_user_turn_strategies", return_value=strategies
            ) as build:
                params = await asyncio.to_thread(bot._build_user_aggregator_params)
        finally:
            bot._BARGEIN_BUILD_CONTEXT.reset(token)
        vad.assert_called_once_with(params=bargein.SMART_VAD_PARAMS)
        build.assert_called_once_with(bargein_mode="smart", trace=trace)
        self.assertIs(params.user_turn_strategies, strategies)


if __name__ == "__main__":
    unittest.main()
