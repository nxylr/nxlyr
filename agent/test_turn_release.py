import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.frames.frames import (
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.turns.user_start import UserTurnStartedParams
from pipecat.turns.user_turn_controller import UserTurnController
from pipecat.utils.asyncio.task_manager import TaskManager


AGENT_DIRECTORY = str(Path(__file__).parent)
if AGENT_DIRECTORY not in sys.path:
    sys.path.insert(0, AGENT_DIRECTORY)


class FakeClock:
    """Advanceable replacement for the timeout strategy's asyncio.sleep."""

    def __init__(self) -> None:
        self.now = 0.0
        self._waiters: list[tuple[float, asyncio.Future[None]]] = []

    async def sleep(self, delay: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self._waiters.append((self.now + delay, future))
        await future

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for deadline, future in list(self._waiters):
            if deadline <= self.now and not future.done():
                future.set_result(None)


class IncompleteAnalyzer:
    """A deterministic analyzer that never finishes a turn semantically."""

    def __init__(self, params) -> None:
        self.params = params

    @property
    def speech_triggered(self) -> bool:
        return False

    def set_sample_rate(self, sample_rate: int) -> None:
        pass

    def update_vad_start_secs(self, vad_start_secs: float) -> None:
        pass

    def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
        return EndOfTurnState.INCOMPLETE

    async def analyze_end_of_turn(self):
        return EndOfTurnState.INCOMPLETE, None

    def clear(self) -> None:
        pass

    async def cleanup(self) -> None:
        pass


def import_bot(environment: dict[str, str] | None = None):
    sys.modules.pop("bot", None)
    with (
        patch.dict(os.environ, environment or {}, clear=True),
        patch("dotenv.load_dotenv"),
    ):
        return importlib.import_module("bot")


class TurnReleaseConfigurationTests(unittest.TestCase):
    def test_unset_configuration_builds_smart_turn_then_timeout(self) -> None:
        bot = import_bot()
        recorded_params = []

        strategies = bot.build_user_turn_strategies(
            turn_analyzer_factory=lambda params: recorded_params.append(params)
            or IncompleteAnalyzer(params)
        )

        self.assertEqual(bot.TURN_RELEASE_CONFIG.mode, "smart_backstop")
        self.assertEqual(bot.TURN_RELEASE_CONFIG.backstop_secs, 0.8)
        self.assertEqual(len(strategies.stop), 2)
        self.assertEqual(recorded_params[0].stop_secs, 1.0)
        self.assertEqual(strategies.stop[1]._user_speech_timeout, 0.8)
        self.assertTrue(strategies.stop[0].wait_for_transcript)
        self.assertTrue(strategies.stop[1].wait_for_transcript)

    def test_override_and_boundary_backstops_are_accepted(self) -> None:
        for backstop in ("0.3", "1.2", "2.0"):
            with self.subTest(backstop=backstop):
                bot = import_bot({"NXLYR_TURN_BACKSTOP_SECS": backstop})
                strategies = bot.build_user_turn_strategies(
                    turn_analyzer_factory=IncompleteAnalyzer
                )
                self.assertEqual(bot.TURN_RELEASE_CONFIG.backstop_secs, float(backstop))
                self.assertEqual(
                    strategies.stop[0]._turn_analyzer.params.stop_secs,
                    float(backstop) + 0.2,
                )
                self.assertEqual(strategies.stop[1]._user_speech_timeout, float(backstop))

    def test_blank_mode_and_backstop_use_defaults(self) -> None:
        for environment in (
            {"NXLYR_TURN_MODE": ""},
            {"NXLYR_TURN_BACKSTOP_SECS": ""},
        ):
            with self.subTest(environment=environment):
                config = import_bot(environment).TURN_RELEASE_CONFIG
                self.assertEqual(config.mode, "smart_backstop")
                self.assertEqual(config.backstop_secs, 0.8)

    def test_invalid_nonblank_backstop_fails_during_module_startup(self) -> None:
        for invalid in ("not-a-number", "nan", "inf", "0.29", "2.01"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    RuntimeError, r"NXLYR_TURN_BACKSTOP_SECS.*0.3.*2.0"
                ):
                    import_bot({"NXLYR_TURN_BACKSTOP_SECS": invalid})

    def test_logs_the_active_configuration_at_module_startup(self) -> None:
        with patch("loguru.logger.info") as info:
            import_bot()

        info.assert_called_once_with(
            "turn release configured: mode=smart_backstop backstop_secs=0.8"
        )

    def test_invalid_mode_fails_during_module_startup_before_a_call(self) -> None:
        with self.assertRaisesRegex(
            RuntimeError, r"NXLYR_TURN_MODE.*smart_backstop.*speech_timeout"
        ):
            import_bot({"NXLYR_TURN_MODE": "not-a-mode"})

    def test_speech_timeout_mode_uses_fixed_timer_without_smart_turn(self) -> None:
        bot = import_bot(
            {
                "NXLYR_TURN_MODE": "speech_timeout",
                "NXLYR_TURN_BACKSTOP_SECS": "1.2",
            }
        )

        strategies = bot.build_user_turn_strategies(
            turn_analyzer_factory=lambda params: self.fail("Smart Turn must not be built")
        )

        self.assertEqual(len(strategies.stop), 1)
        self.assertEqual(strategies.stop[0]._user_speech_timeout, 0.6)
        self.assertTrue(strategies.stop[0].wait_for_transcript)

    def test_factory_rejects_a_smart_turn_guard_under_point_two_seconds(self) -> None:
        bot = import_bot()

        with self.assertRaisesRegex(RuntimeError, r"smart_turn_stop_secs.*0.2"):
            bot.build_user_turn_strategies(
                turn_analyzer_factory=IncompleteAnalyzer,
                smart_turn_guard_secs=0.19,
            )

    def test_start_strategies_and_vad_analyzer_match_existing_configuration(self) -> None:
        bot = import_bot()
        strategies = bot.build_user_turn_strategies(
            turn_analyzer_factory=IncompleteAnalyzer
        )

        self.assertEqual(
            [type(strategy) for strategy in strategies.start],
            [bot.VADUserTurnStartStrategy, bot.TranscriptionUserTurnStartStrategy],
        )
        self.assertTrue(strategies.start[0]._enable_interruptions)
        self.assertTrue(strategies.start[1]._enable_interruptions)

        sentinel_analyzer = object()
        with patch.object(bot, "SileroVADAnalyzer", return_value=sentinel_analyzer) as vad:
            params = bot._build_user_aggregator_params(strategies)

        vad.assert_called_once_with()
        self.assertIs(params.vad_analyzer, sentinel_analyzer)


class TurnReleaseLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_logs_the_active_configuration_at_call_start(self) -> None:
        bot = import_bot()

        with (
            patch.object(bot, "check_env"),
            patch.object(
                bot,
                "parse_telephony_websocket",
                new=AsyncMock(side_effect=RuntimeError("stop before call setup")),
            ),
            patch.object(bot.logger, "info") as info,
            self.assertRaisesRegex(RuntimeError, "stop before call setup"),
        ):
            await bot.run_bot(object())

        info.assert_called_once_with(
            "turn release call start: mode=smart_backstop backstop_secs=0.8"
        )


class TurnReleaseTimingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.bot = import_bot()
        self.clock = FakeClock()
        self.real_sleep = asyncio.sleep
        self.sleep_patch = patch(
            "pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy.asyncio.sleep",
            new=self.clock.sleep,
        )
        self.sleep_patch.start()
        self.addAsyncCleanup(self._cleanup_clock_patch)

    async def _cleanup_clock_patch(self) -> None:
        self.sleep_patch.stop()

    async def _drain(self) -> None:
        """The sole event-loop drain permitted after each fake-clock advance."""
        await self.real_sleep(0)

    async def _controller(self, mode: str, backstop_secs: float):
        config = self.bot.TurnReleaseConfig(mode=mode, backstop_secs=backstop_secs)
        strategies = self.bot.build_user_turn_strategies(
            config=config,
            turn_analyzer_factory=IncompleteAnalyzer,
        )
        controller = UserTurnController(
            user_turn_strategies=strategies, user_turn_stop_timeout=30.0
        )
        stops = []

        @controller.event_handler("on_user_turn_stopped")
        async def on_user_turn_stopped(_, strategy, params) -> None:
            stops.append((strategy, params))

        await controller.setup(TaskManager())
        await controller._trigger_user_turn_start(
            None, UserTurnStartedParams(enable_interruptions=True, enable_user_speaking_frames=True)
        )
        self.addAsyncCleanup(controller.cleanup)
        return controller, stops

    async def _finalized_pause(self, controller: UserTurnController) -> None:
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.1))
        await controller.process_frame(
            TranscriptionFrame("done", "user", "0", finalized=True)
        )
        await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
        # Let the newly scheduled fake timer reach its await point before the
        # test advances fake time. Clock advances themselves get one drain.
        await self._drain()

    async def test_smart_backstop_releases_once_at_fake_clock_deadline(self) -> None:
        controller, stops = await self._controller("smart_backstop", 0.8)
        await self._finalized_pause(controller)

        self.clock.advance(0.79)
        await self._drain()
        self.assertEqual(stops, [])
        self.clock.advance(0.01)
        await self._drain()

        self.assertEqual(self.clock.now, 0.8)
        self.assertEqual(len(stops), 1)

    async def test_resume_before_deadline_cancels_then_later_pause_releases_once(self) -> None:
        controller, stops = await self._controller("smart_backstop", 0.8)
        await self._finalized_pause(controller)

        self.clock.advance(0.4)
        await self._drain()
        await controller.process_frame(VADUserStartedSpeakingFrame(start_secs=0.1))
        self.clock.advance(1.0)
        await self._drain()
        self.assertEqual(stops, [])

        await controller.process_frame(
            TranscriptionFrame("continued", "user", "1", finalized=True)
        )
        await controller.process_frame(VADUserStoppedSpeakingFrame(stop_secs=0.2))
        await self._drain()
        self.clock.advance(0.8)
        await self._drain()
        self.assertEqual(len(stops), 1)

    async def test_speech_timeout_does_not_release_before_fixed_deadline(self) -> None:
        controller, stops = await self._controller("speech_timeout", 1.2)
        await self._finalized_pause(controller)

        self.clock.advance(0.59)
        await self._drain()
        self.assertEqual(stops, [])
        self.clock.advance(0.01)
        await self._drain()

        self.assertEqual(self.clock.now, 0.6)
        self.assertEqual(len(stops), 1)
