import asyncio
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import requests


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

with patch("dotenv.load_dotenv"):
    import bot
    import convo_config
    import kb_loader
    import log_scrub
    import server
    import tools

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    ClientConnectedFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection


class StopAfterSetup(RuntimeError):
    pass


class FakeClientSession:
    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self) -> None:
        self.values = {"ws_bind:call-1": json.dumps({"issued_at": 123})}

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class FakeEndpointWebSocket:
    def __init__(self) -> None:
        self.messages = iter(
            [
                {"type": "websocket.receive", "text": json.dumps({"event": "connected"})},
                {
                    "type": "websocket.receive",
                    "text": json.dumps(
                        {"event": "start", "start": {"call_sid": "call-1"}}
                    ),
                },
            ]
        )
        self.app = SimpleNamespace(state=SimpleNamespace(redis=FakeRedis()))
        self.close_codes: list[int | None] = []

    async def accept(self) -> None:
        return None

    async def receive(self):
        return next(self.messages)

    async def close(self, code: int | None = None) -> None:
        self.close_codes.append(code)


def kb_response(project_name: str) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = [
        {
            "id": "project-1",
            "name": project_name,
            "config": {"project_name": project_name},
            "tenants": {"slug": bot.KB_PROJECT_SLUG},
        }
    ]
    return response


async def run_bot_until_models_built(blocking_builder) -> None:
    class Session(FakeClientSession):
        pass

    with (
        patch.object(bot, "check_env"),
        patch.object(
            bot,
            "parse_telephony_websocket",
            new=AsyncMock(
                return_value=(
                    "exotel",
                    SimpleNamespace(stream_id="stream-1", call_id="call-1"),
                )
            ),
        ),
        patch.multiple(
            bot,
            load_project_kb=MagicMock(return_value={"project_name": "Test"}),
            read_convo_config=AsyncMock(return_value=convo_config.ConvoConfig()),
        ),
        patch.object(bot, "ExotelFrameSerializer"),
        patch.object(bot, "FastAPIWebsocketParams"),
        patch.object(bot, "FastAPIWebsocketTransport"),
        patch.object(bot, "STTCheckingDeepgramService"),
        patch.object(bot, "OpenAILLMService"),
        patch.object(bot.aiohttp, "ClientSession", Session),
        patch.object(bot, "ElevenLabsHttpTTSService"),
        patch.object(
            bot,
            "build_initial_messages",
            return_value=[{"content": "system"}, {"content": "greeting"}],
        ),
        patch.object(bot, "LLMContext"),
        patch.object(bot, "_build_user_aggregator_params", side_effect=blocking_builder),
        patch.object(
            bot, "LLMContextAggregatorPair", side_effect=StopAfterSetup("models built")
        ),
    ):
        with unittest.TestCase().assertRaisesRegex(StopAfterSetup, "models built"):
            await bot.run_bot(object(), ws_connected_at=time.monotonic(), conn_id="abcdef")


async def capture_completed_bot_timing_lines() -> list[str]:
    class FakeTransport:
        def __init__(self) -> None:
            self.handlers = {}

        def input(self):
            return object()

        def output(self):
            return object()

        def event_handler(self, event_name):
            def register(handler):
                self.handlers[event_name] = handler
                return handler

            return register

    class FakeWorker:
        def __init__(self, *args, observers, **kwargs) -> None:
            self.observers = observers
            self.queued_frames = []

        async def queue_frames(self, frames) -> None:
            self.queued_frames.extend(frames)

        async def cancel(self) -> None:
            return None

    class FakeRunner:
        def __init__(self, transport) -> None:
            self.transport = transport
            self.worker = None

        async def add_workers(self, worker) -> None:
            self.worker = worker

        async def run(self) -> None:
            await self.transport.handlers["on_client_connected"](
                self.transport, object()
            )
            for observer in self.worker.observers:
                await observer.on_push_frame(
                    FramePushed(
                        source=None,
                        destination=None,
                        frame=VADUserStartedSpeakingFrame(),
                        direction=FrameDirection.DOWNSTREAM,
                        timestamp=0,
                    )
                )
                await observer.on_push_frame(
                    FramePushed(
                        source=None,
                        destination=None,
                        frame=BotStartedSpeakingFrame(),
                        direction=FrameDirection.DOWNSTREAM,
                        timestamp=0,
                    )
                )

    class FakeAggregator:
        def user(self):
            return object()

        def assistant(self):
            return object()

    transport = FakeTransport()
    runner = FakeRunner(transport)
    with (
        patch.object(bot, "check_env"),
        patch.object(
            bot,
            "parse_telephony_websocket",
            new=AsyncMock(
                return_value=(
                    "exotel",
                    SimpleNamespace(stream_id="stream-1", call_id="call-1"),
                )
            ),
        ),
        patch.multiple(
            bot,
            load_project_kb=MagicMock(return_value={"project_name": "Test"}),
            read_convo_config=AsyncMock(return_value=convo_config.ConvoConfig()),
        ),
        patch.object(bot, "ExotelFrameSerializer"),
        patch.object(bot, "FastAPIWebsocketParams"),
        patch.object(bot, "FastAPIWebsocketTransport", return_value=transport),
        patch.object(bot, "STTCheckingDeepgramService"),
        patch.object(bot, "OpenAILLMService"),
        patch.object(bot.aiohttp, "ClientSession", FakeClientSession),
        patch.object(bot, "ElevenLabsHttpTTSService"),
        patch.object(
            bot,
            "build_initial_messages",
            return_value=[{"content": "system"}, {"content": "greeting"}],
        ),
        patch.object(bot, "LLMContext"),
        patch.object(bot, "_build_user_aggregator_params", return_value=object()),
        patch.object(bot, "LLMContextAggregatorPair", return_value=FakeAggregator()),
        patch.object(bot, "Pipeline"),
        patch.object(bot, "PipelineParams"),
        patch.object(bot, "PipelineWorker", side_effect=FakeWorker),
        patch.object(bot, "WorkerRunner", return_value=runner),
        patch.object(bot, "make_redis_client", new=AsyncMock(return_value=None)),
        patch.object(bot.logger, "info") as info,
    ):
        await bot.run_bot(
            object(), ws_connected_at=time.monotonic(), conn_id="abcdef"
        )

    return [
        str(call.args[0])
        for call in info.call_args_list
        if call.args and str(call.args[0]).startswith("call timing:")
    ]


class StartupAndRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        kb_loader._kb_cache.clear()

    async def test_t1_lifespan_preloads_kb_before_serving(self) -> None:
        app = SimpleNamespace(state=SimpleNamespace())
        session = FakeClientSession()
        env = {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(server.aiohttp, "ClientSession", return_value=session),
            patch.object(kb_loader.requests, "get", return_value=kb_response("Preloaded")) as get,
        ):
            async with server.lifespan(app):
                self.assertEqual(get.call_count, 1)
                self.assertEqual(
                    kb_loader.load_kb(bot.KB_PROJECT_SLUG)["project_name"], "Preloaded"
                )
                self.assertEqual(get.call_count, 1)

        self.assertTrue(session.closed)

    async def test_t2_refreshes_and_keeps_last_good_kb_on_every_failure(self) -> None:
        app = SimpleNamespace(state=SimpleNamespace())
        real_sleep = asyncio.sleep
        blocker = asyncio.Event()
        sleep_calls = 0
        clock = {"now": 0.0}

        async def controlled_sleep(seconds: float) -> None:
            nonlocal sleep_calls
            self.assertEqual(seconds, 240)
            sleep_calls += 1
            if sleep_calls == 1:
                clock["now"] = 240.0
                return
            if sleep_calls == 2:
                clock["now"] = 541.0
                return
            if sleep_calls == 3:
                clock["now"] = 781.0
                return
            await blocker.wait()

        get = MagicMock(
            side_effect=[
                kb_response("Initial"),
                kb_response("Refreshed"),
                requests.ConnectionError("secret-one https://private.example"),
                requests.ConnectionError("secret-two KB-CONTENT"),
            ]
        )
        env = {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(server.aiohttp, "ClientSession", return_value=FakeClientSession()),
            patch.object(server.asyncio, "sleep", new=controlled_sleep),
            patch.object(kb_loader, "monotonic", side_effect=lambda: clock["now"]),
            patch.object(kb_loader.requests, "get", get),
            patch.object(server.logger, "warning") as warning,
        ):
            async with server.lifespan(app):
                for _ in range(100):
                    if get.call_count >= 4:
                        break
                    await real_sleep(0)
                self.assertEqual(get.call_count, 4)
                for _ in range(100):
                    refresh_warning_count = sum(
                        1
                        for call in warning.call_args_list
                        if call.args and "KB refresh failed" in str(call.args[0])
                    )
                    if refresh_warning_count >= 2:
                        break
                    await real_sleep(0)
                before_call = get.call_count
                self.assertEqual(
                    kb_loader.load_kb(bot.KB_PROJECT_SLUG)["project_name"],
                    "Refreshed",
                )
                self.assertEqual(get.call_count, before_call)

            refresh_warnings = [
                str(call.args[0])
                for call in warning.call_args_list
                if call.args and "KB refresh failed" in str(call.args[0])
            ]

        self.assertEqual(len(refresh_warnings), 2)
        self.assertIn("cache_age_seconds=301", refresh_warnings[0])
        self.assertIn("cache_age_seconds=541", refresh_warnings[1])
        for message in refresh_warnings:
            self.assertNotIn("secret-", message)
            self.assertNotIn("://", message)
            self.assertNotIn("KB-CONTENT", message)
        warning.assert_any_call("Serving stale KB cache_age_seconds=541")

        active_refresh_tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name() == "kb-refresh"
            and not task.done()
        ]
        self.assertEqual(active_refresh_tasks, [])

    async def test_t2_failed_initial_preload_does_not_stop_startup(self) -> None:
        app = SimpleNamespace(state=SimpleNamespace())
        real_sleep = asyncio.sleep
        blocker = asyncio.Event()
        sleep_calls = 0

        async def controlled_sleep(seconds: float) -> None:
            nonlocal sleep_calls
            self.assertEqual(seconds, 240)
            sleep_calls += 1
            if sleep_calls == 1:
                return
            await blocker.wait()

        env = {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(server.aiohttp, "ClientSession", return_value=FakeClientSession()),
            patch.object(server.asyncio, "sleep", new=controlled_sleep),
            patch.object(
                kb_loader.requests,
                "get",
                side_effect=requests.ConnectionError("secret https://private.example"),
            ),
            patch.object(server.logger, "error") as error,
            patch.object(server.logger, "warning") as warning,
        ):
            async with server.lifespan(app):
                self.assertTrue(hasattr(app.state, "session"))
                for _ in range(100):
                    no_cache_warning = any(
                        call.args
                        and "cache_age_seconds=none" in str(call.args[0])
                        for call in warning.call_args_list
                    )
                    if no_cache_warning:
                        break
                    await real_sleep(0)

        preload_errors = [
            str(call.args[0])
            for call in error.call_args_list
            if call.args and "KB preload failed" in str(call.args[0])
        ]
        self.assertEqual(len(preload_errors), 1)
        self.assertNotIn("secret", preload_errors[0])
        self.assertNotIn("://", preload_errors[0])
        self.assertTrue(no_cache_warning)


class NonBlockingCallSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_t3_cold_kb_load_does_not_block_the_event_loop(self) -> None:
        ticks = 0
        stop = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        def slow_kb_load():
            time.sleep(0.5)
            return {"project_name": "Test"}

        ticker_task = asyncio.create_task(ticker())
        try:
            with (
                patch.object(bot, "check_env"),
                patch.object(
                    bot,
                    "parse_telephony_websocket",
                    new=AsyncMock(
                        return_value=(
                            "exotel",
                            SimpleNamespace(stream_id="stream-1", call_id="call-1"),
                        )
                    ),
                ),
                patch.object(bot, "load_project_kb", side_effect=slow_kb_load),
                patch.object(
                    bot,
                    "ExotelFrameSerializer",
                    side_effect=StopAfterSetup("kb loaded"),
                ),
                self.assertRaisesRegex(StopAfterSetup, "kb loaded"),
            ):
                await bot.run_bot(
                    object(), ws_connected_at=time.monotonic(), conn_id="abcdef"
                )
        finally:
            stop.set()
            await ticker_task

        self.assertGreaterEqual(ticks, 30)

    async def test_t4_model_build_does_not_block_the_event_loop(self) -> None:
        ticks = 0
        stop = asyncio.Event()

        async def ticker() -> None:
            nonlocal ticks
            while not stop.is_set():
                ticks += 1
                await asyncio.sleep(0.01)

        def slow_analyzer(*args, **kwargs):
            time.sleep(0.2)
            return object()

        def build_models():
            bot.SileroVADAnalyzer()
            bot.LocalSmartTurnAnalyzerV3()
            return object()

        ticker_task = asyncio.create_task(ticker())
        try:
            with (
                patch.object(bot, "SileroVADAnalyzer", side_effect=slow_analyzer),
                patch.object(
                    bot, "LocalSmartTurnAnalyzerV3", side_effect=slow_analyzer
                ),
            ):
                await run_bot_until_models_built(build_models)
        finally:
            stop.set()
            await ticker_task

        self.assertGreaterEqual(ticks, 30)

    async def test_t4b_models_built_is_logged_once_per_call(self) -> None:
        with patch.object(bot.logger, "info") as info:
            await run_bot_until_models_built(lambda: object())

        lines = [
            str(call.args[0])
            for call in info.call_args_list
            if call.args and str(call.args[0]).startswith("call timing: models_built")
        ]
        self.assertEqual(len(lines), 1)
        self.assertRegex(
            lines[0],
            r"^call timing: models_built conn=abcdef t_ms=\d+ models_ms=\d+$",
        )


class TimeoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        kb_loader._kb_cache.clear()

    def test_t5_kb_fetch_uses_split_connect_and_read_timeout(self) -> None:
        env = {
            "SUPABASE_URL": "https://fake.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "fake-key",
        }
        with (
            patch.dict(os.environ, env, clear=False),
            patch.object(kb_loader.requests, "get", return_value=kb_response("Test")) as get,
        ):
            kb_loader.load_kb(bot.KB_PROJECT_SLUG)

        self.assertEqual(get.call_args.kwargs["timeout"], (2.0, 5.0))

    async def test_t6_redis_clients_have_socket_timeouts_and_ping_cap(self) -> None:
        class HangingClient:
            def __init__(self):
                self.closed = False

            async def ping(self):
                await asyncio.sleep(10)

            async def aclose(self):
                self.closed = True

        hanging = HangingClient()
        started = time.monotonic()
        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://example"}, clear=False),
            patch("redis.asyncio.from_url", return_value=hanging) as from_url,
            patch.object(tools.logger, "error") as error,
        ):
            self.assertIsNone(await tools.make_redis_client())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(from_url.call_args.kwargs["socket_connect_timeout"], 1.0)
        self.assertEqual(from_url.call_args.kwargs["socket_timeout"], 2.0)
        error.assert_called_once()
        self.assertTrue(hanging.closed)

        class HealthyClient:
            async def ping(self):
                return True

        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
        with (
            patch.dict(os.environ, {"REDIS_URL": "redis://example"}, clear=False),
            patch("redis.asyncio.from_url", return_value=HealthyClient()) as from_url,
        ):
            await server.get_demo_redis_client(request, ping_timeout_seconds=0.1)

        self.assertEqual(from_url.call_args.kwargs["socket_connect_timeout"], 1.0)
        self.assertEqual(from_url.call_args.kwargs["socket_timeout"], 2.0)


class CallTimingLogTests(unittest.IsolatedAsyncioTestCase):
    async def test_t7_websocket_log_precedes_run_bot_and_passes_timing(self) -> None:
        websocket = FakeEndpointWebSocket()
        order: list[str] = []

        def record_info(message, *args) -> None:
            rendered = str(message).format(*args)
            if rendered.startswith("call timing: ws_connected"):
                order.append(rendered)

        async def record_run_bot(*args, **kwargs) -> None:
            order.append("run_bot")

        with (
            patch.dict(os.environ, {"WS_AUTH_MODE": "enforce"}, clear=False),
            patch.object(server, "ws_admission_counter", server.AdmissionCounter()),
            patch.object(server.secrets, "token_hex", return_value="abcdef"),
            patch.object(server, "monotonic", return_value=123.0),
            patch.object(server.logger, "info", side_effect=record_info),
            patch.object(server, "run_bot", new=AsyncMock(side_effect=record_run_bot)) as run_bot,
        ):
            await server.websocket_endpoint(websocket)

        self.assertEqual(order, ["call timing: ws_connected conn=abcdef t_ms=0", "run_bot"])
        self.assertEqual(run_bot.await_args.kwargs["ws_connected_at"], 123.0)
        self.assertEqual(run_bot.await_args.kwargs["conn_id"], "abcdef")

    async def push(self, observer, frame) -> None:
        await observer.on_push_frame(
            FramePushed(
                source=None,
                destination=None,
                frame=frame,
                direction=FrameDirection.DOWNSTREAM,
                timestamp=0,
            )
        )

    async def test_t8_first_greeting_audio_is_logged_exactly_once(self) -> None:
        observer = bot.CallTimingObserver(ws_connected_at=100.0, conn_id="abcdef")
        with (
            patch.object(bot, "monotonic", return_value=100.25),
            patch.object(bot.logger, "info") as info,
        ):
            await self.push(observer, ClientConnectedFrame())
            await self.push(observer, BotStartedSpeakingFrame())
            await self.push(observer, BotStartedSpeakingFrame())

        lines = [
            str(call.args[0])
            for call in info.call_args_list
            if call.args and "first_bot_audio_sent" in str(call.args[0])
        ]
        self.assertEqual(lines, ["call timing: first_bot_audio_sent conn=abcdef t_ms=250"])

    async def test_t9_caller_speaking_before_greeting_is_distinguishable(self) -> None:
        observer = bot.CallTimingObserver(ws_connected_at=100.0, conn_id="abcdef")
        with (
            patch.object(bot, "monotonic", return_value=100.25),
            patch.object(bot.logger, "info") as info,
        ):
            await self.push(observer, VADUserStartedSpeakingFrame())
            await self.push(observer, VADUserStartedSpeakingFrame())
            await self.push(observer, BotStartedSpeakingFrame())

        lines = [
            str(call.args[0])
            for call in info.call_args_list
            if call.args and str(call.args[0]).startswith("call timing:")
        ]
        self.assertEqual(
            lines,
            [
                "call timing: caller_spoke_before_greeting_audio conn=abcdef t_ms=250",
                "call timing: first_bot_audio_sent conn=abcdef t_ms=250",
            ],
        )

        silent = bot.CallTimingObserver(ws_connected_at=100.0, conn_id="abcdef")
        with (
            patch.object(bot, "monotonic", return_value=100.25),
            patch.object(bot.logger, "info") as silent_info,
        ):
            await self.push(silent, BotStartedSpeakingFrame())
        self.assertNotIn("caller_spoke", str(silent_info.call_args_list))

    async def test_setup_done_and_greeting_queued_are_logged(self) -> None:
        lines = await capture_completed_bot_timing_lines()
        events = [line.split()[2] for line in lines]
        self.assertEqual(events.count("setup_done"), 1)
        self.assertEqual(events.count("greeting_queued"), 1)
        self.assertLess(events.index("setup_done"), events.index("greeting_queued"))

    async def test_t10_all_call_timing_lines_are_safe_and_scrub_stable(self) -> None:
        lines = await capture_completed_bot_timing_lines()
        self.assertEqual(
            {line.split()[2] for line in lines},
            {
                "models_built",
                "setup_done",
                "greeting_queued",
                "caller_spoke_before_greeting_audio",
                "first_bot_audio_sent",
            },
        )
        pattern = re.compile(
            r"^call timing: [a-z_]+ conn=[0-9a-f]{6} t_ms=\d+"
            r"( [a-z_]+=[a-z0-9]+)*$"
        )
        for line in lines:
            self.assertRegex(line, pattern)
            self.assertNotRegex(line, r"\d{7,}")
            self.assertNotIn("@", line)
            self.assertNotIn("://", line)
            self.assertNotIn("Bearer", line)
            self.assertEqual(log_scrub.scrub(line), line)
if __name__ == "__main__":
    unittest.main()
