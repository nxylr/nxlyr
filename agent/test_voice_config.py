"""Voice-config acceptance tests. All external services are fakes."""

import asyncio
import inspect
import os
import sys
import time
import unittest
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

with patch("dotenv.load_dotenv"):
    import bot
    import log_scrub
    import prompt
    import server
    import voice_config as vc

from test_convo_config import run_wired_bot
import convo_config

from pipecat.services.elevenlabs.tts import (
    ElevenLabsHttpTTSService,
    ElevenLabsHttpTTSSettings,
    build_elevenlabs_voice_settings,
)


class FakeResponse:
    def __init__(self, status=200, delay=0):
        self.status = status
        self.delay = delay
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read(self, n=-1):
        if self.delay:
            await asyncio.sleep(self.delay)
        return b"x" if n == 1 else b""

    async def text(self):
        return "fake response body"


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.requests = []

    def post(self, url, **kwargs):
        self.requests.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        return None


class FakeClientSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class StopAfterGreeting(Exception):
    pass


async def drive_call(override, environment):
    """Run the real TTS setup, then stop before pipeline construction."""
    captured = {}

    def capture_messages(*args, **kwargs):
        captured["locals"] = sys._getframe(1).f_locals.copy()
        return [{"content": "system"}, {"content": "greeting"}]

    def capture_tts(**kwargs):
        captured["settings"] = kwargs["settings"]
        captured["filters"] = kwargs["text_filters"]
        return object()

    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(bot, "check_env"),
        patch.object(bot, "parse_telephony_websocket", new=AsyncMock(return_value=(
            "exotel", SimpleNamespace(stream_id="stream-1", call_id="call-1")
        ))),
        patch.object(bot, "load_project_kb", return_value={"project_name": "Test"}),
        patch.object(bot, "ExotelFrameSerializer"),
        patch.object(bot, "FastAPIWebsocketParams"),
        patch.object(bot, "FastAPIWebsocketTransport"),
        patch.object(bot, "STTCheckingDeepgramService"),
        patch.object(bot, "OpenAILLMService"),
        patch.object(bot, "read_convo_config", new=AsyncMock(return_value=convo_config.ConvoConfig())),
        patch.object(bot.aiohttp, "ClientSession", FakeClientSession),
        patch.object(bot, "read_override", new=AsyncMock(return_value=override)),
        patch.object(bot, "ElevenLabsHttpTTSService", side_effect=capture_tts),
        patch.object(bot, "build_initial_messages", new=capture_messages),
        patch.object(bot, "LLMContext", side_effect=StopAfterGreeting),
        patch.object(bot.logger, "info") as info,
    ):
        with unittest.TestCase().assertRaises(StopAfterGreeting):
            await bot.run_bot(object(), conn_id="abcdef")
    captured["lines"] = [
        call.args[0] for call in info.call_args_list
        if call.args and str(call.args[0]).startswith("voice config:")
    ]
    return captured


class VoiceConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_v1_no_override_matches_current_settings_and_http_request(self):
        for environment, model, voice in (
            ({}, "eleven_turbo_v2", "21m00Tcm4TlvDq8ikWAM"),
            ({"ELEVENLABS_MODEL": "eleven_flash_v2_5",
              "ELEVENLABS_VOICE_ID": "GQrVSQduiFCVTMHGavV5"},
             "eleven_flash_v2_5", "GQrVSQduiFCVTMHGavV5"),
        ):
            with self.subTest(model=model):
                cfg = vc.resolve(None, environment)
                expected = ElevenLabsHttpTTSSettings(model=model, voice=voice)
                actual = vc.to_settings(cfg)
                self.assertEqual(cfg.overrides, ())
                self.assertEqual(vc.dropped_fields(cfg), ())
                self.assertTrue(all(getattr(cfg, n) is None for n in vc.SETTING_FIELDS))
                self.assertEqual(
                    {f.name: getattr(actual, f.name) for f in fields(actual)},
                    {f.name: getattr(expected, f.name) for f in fields(expected)},
                )
                requests = []
                for settings in (expected, actual):
                    session = FakeSession(FakeResponse(status=500))
                    service = ElevenLabsHttpTTSService(
                        api_key="fake-key", aiohttp_session=session,
                        sample_rate=8000, settings=settings,
                    )
                    service._output_format = "pcm_8000"
                    async for _ in service.run_tts("Hi.", "fake-context"):
                        pass
                    requests.append(session.requests[0])
                self.assertEqual(requests[0], requests[1])
                self.assertNotIn("voice_settings", requests[0][1]["json"])
                self.assertNotIn("optimize_streaming_latency", requests[0][1]["params"])
                print(f"V1 {model}: raw settings equal; HTTP payload and params equal: {requests[0][1]['json']}, {requests[0][1]['params']}")

    async def test_v2_precedence_is_per_field(self):
        cfg = vc.resolve(
            {"model": "eleven_v4_turbo", "stability": "0.5"},
            {"ELEVENLABS_MODEL": "eleven_flash_v2_5",
             "ELEVENLABS_VOICE_ID": "GQrVSQduiFCVTMHGavV5"},
        )
        self.assertEqual((cfg.model, cfg.voice, cfg.stability, cfg.speed),
                         ("eleven_v4_turbo", "GQrVSQduiFCVTMHGavV5", 0.5, None))
        self.assertEqual(cfg.overrides, ("model", "stability"))

    async def test_v3_invalid_values_fall_back_per_field_without_logging_values(self):
        invalid = {
            "stability": ("1.5", "-0.1", "abc", "nan", "inf", ""),
            "speed": ("0.5", "2"), "use_speaker_boost": ("maybe",),
            "optimize_streaming_latency": ("5", "1.5"),
            "model": ("eleven_v3_conversational", "unknown"),
            "voice": ("not valid", "abc"), "provider": ("openai",),
            "keepwarm_seconds": ("30",),
        }
        valid_env = {
            "ELEVENLABS_MODEL": "eleven_flash_v2_5",
            "ELEVENLABS_VOICE_ID": "GQrVSQduiFCVTMHGavV5",
            "ELEVENLABS_STABILITY": "0.4", "ELEVENLABS_SPEED": "1.0",
            "ELEVENLABS_USE_SPEAKER_BOOST": "false",
            "ELEVENLABS_OPTIMIZE_STREAMING_LATENCY": "2",
        }
        for name, values in invalid.items():
            for bad in values:
                with self.subTest(name=name, bad=bad):
                    with patch.object(vc.logger, "warning") as warning:
                        cfg = vc.resolve({name: bad, "similarity_boost": "0.75"}, valid_env)
                    self.assertEqual(warning.call_count, 1)
                    self.assertEqual(warning.call_args.args[1], name)
                    if bad:
                        self.assertNotIn(bad, warning.call_args.args[0])
                    self.assertEqual(cfg.similarity_boost, 0.75)
                    fallback = vc.resolve(None, valid_env)
                    self.assertEqual(getattr(cfg, name), getattr(fallback, name))
        with patch.object(vc.logger, "warning") as warning:
            cfg = vc.resolve(None, {"ELEVENLABS_STABILITY": "nan"})
        self.assertIsNone(cfg.stability)
        self.assertEqual(warning.call_count, 1)

    async def test_f2_blank_env_is_unset_without_warning(self):
        blank_env = {env_name: "" for env_name in vc.ENV_NAMES.values()}
        with patch.object(vc.logger, "warning") as warning:
            cfg = vc.resolve(None, blank_env)
        self.assertEqual(cfg, vc.VoiceConfig())
        warning.assert_not_called()
        with patch.object(vc.logger, "warning") as warning:
            cfg = vc.resolve({"stability": ""}, {"ELEVENLABS_STABILITY": ""})
        self.assertIsNone(cfg.stability)
        warning.assert_called_once_with(
            "Invalid voice:config value for {}; using fallback", "stability"
        )
        with patch.object(vc.logger, "warning") as warning:
            cfg = vc.resolve(None, {"ELEVENLABS_STABILITY": "not-a-number"})
        self.assertIsNone(cfg.stability)
        warning.assert_called_once_with(
            "Invalid voice:config value for {}; using fallback", "stability"
        )

    async def test_v4_unknown_field_warns_once(self):
        with patch.object(vc.logger, "warning") as warning:
            cfg = vc.resolve({"stabilty": "0.5"}, {})
        self.assertEqual(warning.call_count, 1)
        self.assertEqual(warning.call_args.args[1], "stabilty")
        self.assertIsNone(cfg.stability)

    async def test_v5_redis_unavailable_error_and_timeout_close_client(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(vc.logger, "warning") as warn:
            self.assertIsNone(await vc.read_override())
            self.assertIn("MissingRedisURL", warn.call_args.args[0])

        class Redis:
            def __init__(self, mode):
                self.mode = mode
                self.closed = False

            async def hgetall(self, name):
                if self.mode == "error":
                    raise RuntimeError("secret response body")
                await asyncio.sleep(10)

            async def aclose(self):
                self.closed = True

        for mode in ("error", "hang"):
            client = Redis(mode)
            start = time.monotonic()
            with patch.object(vc.logger, "warning") as warn:
                self.assertIsNone(await vc.read_override(client))
            self.assertLess(time.monotonic() - start, 1.5)
            self.assertTrue(client.closed)
            line = warn.call_args.args[0]
            self.assertNotIn("secret response body", line)
            self.assertIn("error_type=", line)

    async def test_f4_quiet_redis_read_has_no_connected_info_line(self):
        class Redis:
            closed = False

            async def hgetall(self, key):
                self.key = key
                return {"model": "eleven_v4_turbo"}

            async def aclose(self):
                self.closed = True

        client = Redis()
        with (patch.dict(os.environ, {"REDIS_URL": "redis://fake-host"}, clear=True),
              patch("redis.asyncio.from_url", return_value=client) as factory,
              patch.object(vc, "make_redis_client", new=AsyncMock()) as noisy_factory,
              patch.object(vc.logger, "info") as info):
            result = await vc.read_override(quiet=True)
        self.assertEqual(result, {"model": "eleven_v4_turbo"})
        self.assertEqual(client.key, "voice:config")
        self.assertTrue(client.closed)
        factory.assert_called_once()
        noisy_factory.assert_not_awaited()
        info.assert_not_called()

    async def test_v6_run_bot_uses_resolved_settings_and_voice_cfg_local(self):
        self.assertIn("voice_cfg = resolve(", inspect.getsource(bot.run_bot))
        no_override = await drive_call(None, {})
        self.assertEqual(no_override["settings"], vc.to_settings(vc.resolve(None, {})))
        self.assertIn("voice_cfg", no_override["locals"])
        self.assertEqual(no_override["locals"]["voice_cfg"].model, "eleven_turbo_v2")
        self.assertEqual(len(no_override["filters"]), 1)
        production = {
            "ELEVENLABS_MODEL": "eleven_flash_v2_5",
            "ELEVENLABS_VOICE_ID": "GQrVSQduiFCVTMHGavV5",
        }
        production_no_override = await drive_call(None, production)
        self.assertEqual(production_no_override["settings"],
                         vc.to_settings(vc.resolve(None, production)))
        flash = await drive_call(
            {"model": "eleven_flash_v2_5", "stability": "0.45",
             "similarity_boost": "0.75", "speed": "1.0"}, {}
        )
        self.assertEqual((flash["settings"].model, flash["settings"].stability,
                          flash["settings"].similarity_boost, flash["settings"].speed),
                         ("eleven_flash_v2_5", 0.45, 0.75, 1.0))
        self.assertIn("voice_cfg", flash["locals"])
        print(f"V6 no override: {no_override['lines'][0]}")
        print(f"V6 production no override: {production_no_override['lines'][0]}")
        print(f"V6 Flash override: {flash['lines'][0]}")

    async def test_v7_v4_drops_unsupported_fields_flash_sends_them(self):
        base = {"stability": "0.5", "similarity_boost": "0.75", "style": "0.3",
                "speed": "0.95", "use_speaker_boost": "true"}
        v4 = await drive_call({"model": "eleven_v4_turbo", **base}, {})
        settings = v4["settings"]
        self.assertEqual((settings.stability, settings.similarity_boost), (0.5, 0.75))
        self.assertEqual(
            build_elevenlabs_voice_settings(vc.sent_fields(v4["locals"]["voice_cfg"])),
            {"stability": 0.5, "similarity_boost": 0.75},
        )
        for field_name in ("style", "speed", "use_speaker_boost"):
            self.assertEqual(getattr(settings, field_name),
                             getattr(ElevenLabsHttpTTSSettings(), field_name))
        self.assertIn("dropped=style,speed,use_speaker_boost", v4["lines"][0])
        self.assertEqual(v4["filters"], [])
        flash = await drive_call({"model": "eleven_flash_v2_5", **base}, {})
        self.assertEqual((flash["settings"].style, flash["settings"].speed,
                          flash["settings"].use_speaker_boost), (0.3, 0.95, True))
        self.assertIn("dropped=none", flash["lines"][0])
        for model, expected in (("eleven_v4_turbo", False),
                                ("eleven_flash_v2_5", True)):
            result = await drive_call({"model": model,
                                       "optimize_streaming_latency": "2"}, {})
            self.assertEqual("optimize_streaming_latency" in vc.sent_fields(
                result["locals"]["voice_cfg"]), expected)
            self.assertEqual(
                result["settings"].optimize_streaming_latency,
                2 if expected else ElevenLabsHttpTTSSettings().optimize_streaming_latency,
            )
            if not expected:
                self.assertIn("dropped=optimize_streaming_latency", result["lines"][0])
        print(f"V7 v4: {v4['lines'][0]}")
        print(f"V7 Flash: {flash['lines'][0]}")

    async def test_v8_one_scrub_clean_line_per_call(self):
        pattern = (r"^voice config: conn=(?:[0-9a-f]{6}|none) provider=elevenlabs "
                   r"model=\S+ voice=[A-Za-z0-9]+ (?:\w+=\S+ )*"
                   r"overrides=\S+ dropped=\S+$")
        for override in (None, {"model": "eleven_v4_turbo", "speed": "0.9"},
                         {"model": "eleven_flash_v2_5", "stability": "0.45"}):
            call = await drive_call(override, {"ELEVENLABS_API_KEY": "DistinctiveFakeKey987654321"})
            self.assertEqual(len(call["lines"]), 1)
            line = call["lines"][0]
            self.assertRegex(line, pattern)
            self.assertNotIn("DistinctiveFakeKey987654321", line)
            self.assertEqual(log_scrub.scrub(line), line)

    async def test_018_voice_override_selects_greeting_and_both_config_lines(self):
        config = convo_config.parse({"greeting_tags": "on"})
        for model, tagged in (("eleven_v4_turbo", True),
                              ("eleven_flash_v2_5", False)):
            with self.subTest(model=model):
                result = await run_wired_bot(
                    config, active_model="eleven_flash_v2_5",
                    voice_override={"model": model},
                )
            expected = bot.build_greeting(
                bot.LEAD_SOURCE_DEMO_FORM, "Test Heights", tags=tagged
            )
            self.assertEqual(result.frame.text, expected)
            result.tag_guard.assert_called_once_with(model)
            lines = [str(call.args[0]) for call in result.info.call_args_list]
            self.assertEqual(sum(line.startswith("voice config:") for line in lines), 1)
            self.assertEqual(sum(line.startswith("convo config:") for line in lines), 1)
            convo_line = next(line for line in lines if line.startswith("convo config:"))
            self.assertIn("greeting_tags=on" if tagged else "greeting_tags=blocked", convo_line)
            if tagged:
                self.assertIn("[warm]", result.frame.text)
            else:
                self.assertNotIn("[", result.frame.text)
                result.warning.assert_called_once_with(
                    "greeting_tags is on but the voice model is not v4; using the plain greeting"
                )

    async def test_v9_tags_only_removed_for_non_v4_and_plain_text_unchanged(self):
        self.assertEqual(vc.tts_filters(vc.VoiceConfig(model="eleven_v4_turbo")), [])
        for model in ("eleven_flash_v2_5", "eleven_turbo_v2_5",
                      "eleven_turbo_v2", "eleven_multilingual_v2"):
            filters = vc.tts_filters(vc.VoiceConfig(model=model))
            self.assertEqual(len(filters), 1)
            self.assertIsInstance(filters[0], vc.StripTagsFilter)
        strip = vc.StripTagsFilter()
        self.assertEqual(await strip.filter(
            "[warm] Hi, this is Aarya. [reassuring] It is a plan."),
            "Hi, this is Aarya. It is a plan.")
        self.assertEqual(await strip.filter("[CURRENT DATE]"), "")
        self.assertEqual(await strip.filter("[warm]"), "")
        for plain in ("Hi, this is Aarya.", "  Keep  these  spaces.  ",
                      "Aarya's first call.\nNext line."):
            self.assertEqual((await strip.filter(plain)).encode(), plain.encode())
        greeting = prompt.build_initial_messages(
            {"project_name": "Test Heights", "developer": "Test Developer"},
            lead_source=prompt.LEAD_SOURCE_DEMO_FORM,
        )[-1]["content"]
        self.assertEqual((await strip.filter(greeting)).encode(), greeting.encode())

    async def test_v10_keep_warm_request_and_failures_use_only_fakes(self):
        for model, optimize in (("eleven_v4_turbo", False),
                                ("eleven_flash_v2_5", True)):
            cfg = vc.resolve({"model": model, "stability": "0.5",
                              "similarity_boost": "0.75", "style": "0.3",
                              "speed": "0.95", "use_speaker_boost": "true",
                              "optimize_streaming_latency": "2"}, {})
            session = FakeSession()
            ok, ttfb = await vc.keep_warm_once(session, cfg, "fake-key")
            self.assertTrue(ok)
            self.assertGreaterEqual(ttfb, 0)
            url, kwargs = session.requests[0]
            self.assertTrue(url.endswith(f"/{cfg.voice}/stream/with-timestamps"))
            self.assertEqual(kwargs["params"]["output_format"], "pcm_8000")
            self.assertEqual("optimize_streaming_latency" in kwargs["params"], optimize)
            self.assertEqual(kwargs["json"]["model_id"], model)
            self.assertEqual(kwargs["json"]["voice_settings"],
                             build_elevenlabs_voice_settings(vc.sent_fields(cfg)))
            self.assertNotIn("previous_text", kwargs["json"])
            self.assertLessEqual(len(kwargs["json"]["text"]), 5)
            self.assertEqual(kwargs["headers"]["xi-api-key"], "fake-key")
            self.assertNotIn("fake-key", url)
            self.assertNotIn("fake-key", str(kwargs["json"]))
        for status in (500, 401):
            with patch.object(vc.logger, "warning") as warning:
                result = await vc.keep_warm_once(
                    FakeSession(FakeResponse(status=status)), cfg, "fake-key")
            self.assertEqual(result, (False, status))
            self.assertNotIn("fake-key", str(warning.call_args))
            self.assertNotIn("fake response body", str(warning.call_args))
        with patch.object(vc.logger, "warning") as warning:
            result = await vc.keep_warm_once(
                FakeSession(error=vc.aiohttp.ClientError("secret body")), cfg, "fake-key")
        self.assertEqual(result, (False, 0))
        self.assertNotIn("secret body", str(warning.call_args))
        real_timeout = asyncio.timeout
        cap_seen = []

        def short_timeout(cap):
            cap_seen.append(cap)
            return real_timeout(0.01)

        with (patch.object(vc.asyncio, "timeout", side_effect=short_timeout),
              patch.object(vc.logger, "warning") as warning):
            result = await vc.keep_warm_once(FakeSession(FakeResponse(delay=10)), cfg,
                                             "fake-key")
        self.assertEqual(result, (False, 0))
        self.assertEqual(cap_seen, [10])
        self.assertIn("TimeoutError", str(warning.call_args))

    async def test_v11_keep_warm_loop_ticks_reloads_and_cleans_up(self):
        reads = AsyncMock(side_effect=[{}, {"keepwarm_seconds": "60"},
                                       {"keepwarm_seconds": "0"}, {}])
        warm = AsyncMock(side_effect=[(False, 500), (True, 3)])
        intervals = []
        third_wait = asyncio.Event()

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            intervals.append(timeout)
            if len(intervals) < 3:
                raise TimeoutError
            third_wait.set()
            await asyncio.Event().wait()

        app = SimpleNamespace(state=SimpleNamespace(session=FakeSession()))
        with (patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake-key"}, clear=True),
              patch.object(vc, "read_override", reads),
              patch.object(vc, "keep_warm_once", warm),
              patch.object(server, "asyncio", SimpleNamespace(
                  Event=asyncio.Event, wait_for=fake_wait_for))):
            task = asyncio.create_task(server._keep_voice_warm_forever(app))
            await asyncio.wait_for(third_wait.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(intervals, [240, 60, 240])
        self.assertEqual(warm.await_count, 2)
        self.assertTrue(all(call.kwargs == {"quiet": True} for call in reads.await_args_list))

        with (patch.dict(os.environ, {}, clear=True),
              patch.object(vc, "read_override", new=AsyncMock(return_value={})),
              patch.object(vc, "keep_warm_once", new=AsyncMock()) as no_key_warm):
            task = asyncio.create_task(server._keep_voice_warm_forever(app))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            no_key_warm.assert_not_awaited()

        with (patch.dict(os.environ, {}, clear=True),
              patch.object(server.aiohttp, "ClientSession", FakeSession),
              patch.object(server.kb_loader, "load_kb", return_value={}),
              patch.object(vc, "read_override", new=AsyncMock(return_value={}))):
            async with server.lifespan(SimpleNamespace(state=SimpleNamespace())):
                await asyncio.sleep(0)
                self.assertEqual(len([t for t in asyncio.all_tasks()
                                      if t.get_name() == "voice-keepwarm"]), 1)
            self.assertEqual(len([t for t in asyncio.all_tasks()
                                  if t.get_name() == "voice-keepwarm"]), 0)

    async def test_f5_keep_warm_loop_recovers_from_exception_and_logs_ok(self):
        wait_started = asyncio.Event()
        waits = []

        async def fake_wait_for(awaitable, timeout):
            awaitable.close()
            waits.append(timeout)
            if len(waits) == 1:
                raise TimeoutError
            wait_started.set()
            await asyncio.Event().wait()

        warm = AsyncMock(side_effect=[RuntimeError("response body"), (True, 7)])
        app = SimpleNamespace(state=SimpleNamespace(session=FakeSession()))
        with (patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake-key"}, clear=True),
              patch.object(vc, "read_override", new=AsyncMock(return_value={})),
              patch.object(vc, "keep_warm_once", warm),
              patch.object(server, "asyncio", SimpleNamespace(
                  Event=asyncio.Event, wait_for=fake_wait_for)),
              patch.object(server.logger, "warning") as warning,
              patch.object(server.logger, "info") as info):
            task = asyncio.create_task(server._keep_voice_warm_forever(app))
            await asyncio.wait_for(wait_started.wait(), timeout=2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertEqual(warm.await_count, 2)
        self.assertEqual(waits, [240, 240])
        warning.assert_called_once_with(
            "voice keep-warm failed status=none error_type={}", "RuntimeError"
        )
        info.assert_called_once_with(
            "voice keep-warm: ok model={} ttfb_ms={}", "eleven_turbo_v2", 7
        )
