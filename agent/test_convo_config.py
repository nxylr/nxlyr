import asyncio
import io
import os
import re
import sys
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


AGENT_DIR = Path(__file__).parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))

import convo_config
import log_scrub

with patch("dotenv.load_dotenv"):
    import bot

from pipecat.services.settings import is_given


DEFAULTS = {
    "prompt_version": "v2",
    "stt_keyterms": False,
    "stt_numerals": False,
    "stt_region": "global",
    "greeting_tags": False,
}


class FakeRedis:
    def __init__(self, result=None, error: Exception | None = None, delay=0.0) -> None:
        self.result = {} if result is None else result
        self.error = error
        self.delay = delay
        self.closed = False

    async def hgetall(self, key: str):
        self.key = key
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result

    async def aclose(self) -> None:
        self.closed = True


class FakeClientSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


async def run_wired_bot(
    config: convo_config.ConvoConfig,
    *,
    active_model: str | None = None,
    voice_override: dict[str, str] | None = None,
):
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
        def __init__(self, *args, **kwargs) -> None:
            self.queued_frames = []

        async def queue_frames(self, frames) -> None:
            self.queued_frames.extend(frames)

        async def cancel(self) -> None:
            return None

    class FakeAggregator:
        def user(self):
            return object()

        def assistant(self):
            return object()

    transport = FakeTransport()
    worker_box = {}

    def make_worker(*args, **kwargs):
        worker = FakeWorker(*args, **kwargs)
        worker_box["worker"] = worker
        return worker

    class FakeRunner:
        async def add_workers(self, worker) -> None:
            self.worker = worker

        async def run(self) -> None:
            await transport.handlers["on_client_connected"](transport, object())

    with ExitStack() as stack:
        model_env = {"ELEVENLABS_MODEL": active_model} if active_model else {}
        stack.enter_context(patch.dict(os.environ, model_env, clear=True))
        stack.enter_context(patch.object(bot, "check_env"))
        stack.enter_context(patch.object(
            bot,
            "parse_telephony_websocket",
            new=AsyncMock(
                return_value=(
                    "exotel",
                    SimpleNamespace(stream_id="stream-1", call_id="call-1"),
                )
            ),
        ))
        stack.enter_context(patch.object(bot, "load_project_kb", return_value={"project_name": "Test Heights"}))
        stack.enter_context(patch.object(bot, "ExotelFrameSerializer"))
        stack.enter_context(patch.object(bot, "FastAPIWebsocketParams"))
        stack.enter_context(patch.object(bot, "FastAPIWebsocketTransport", return_value=transport))
        stack.enter_context(patch.object(bot, "read_convo_config", new=AsyncMock(return_value=config)))
        stack.enter_context(patch.object(bot, "read_override", new=AsyncMock(return_value=voice_override)))
        stt = stack.enter_context(patch.object(bot, "STTCheckingDeepgramService"))
        stack.enter_context(patch.object(bot, "OpenAILLMService"))
        stack.enter_context(patch.object(bot.aiohttp, "ClientSession", FakeClientSession))
        stack.enter_context(patch.object(bot, "ElevenLabsHttpTTSService"))
        messages = stack.enter_context(patch.object(bot, "build_initial_messages", wraps=bot.build_initial_messages))
        context = stack.enter_context(patch.object(bot, "LLMContext"))
        stack.enter_context(patch.object(bot, "_build_user_aggregator_params", return_value=object()))
        stack.enter_context(patch.object(bot, "LLMContextAggregatorPair", return_value=FakeAggregator()))
        stack.enter_context(patch.object(bot, "Pipeline"))
        stack.enter_context(patch.object(bot, "PipelineParams"))
        stack.enter_context(patch.object(bot, "PipelineWorker", side_effect=make_worker))
        stack.enter_context(patch.object(bot, "WorkerRunner", return_value=FakeRunner()))
        stack.enter_context(patch.object(bot, "make_redis_client", new=AsyncMock(return_value=None)))
        info = stack.enter_context(patch.object(bot.logger, "info"))
        warning = stack.enter_context(patch.object(bot.logger, "warning"))
        tag_guard = stack.enter_context(
            patch.object(bot, "tags_allowed", wraps=bot.tags_allowed)
        )
        await bot.run_bot(object(), conn_id="abcdef")
    return SimpleNamespace(
        frame=worker_box["worker"].queued_frames[0],
        stt=stt,
        messages=messages,
        context=context,
        info=info,
        warning=warning,
        tag_guard=tag_guard,
    )


class ConvoConfigTests(unittest.IsolatedAsyncioTestCase):
    def assert_defaults(self, config: convo_config.ConvoConfig) -> None:
        for field, value in DEFAULTS.items():
            self.assertEqual(getattr(config, field), value)
        self.assertEqual(config.overrides, ())

    async def test_c01_missing_or_empty_hash_uses_every_default(self) -> None:
        for raw in (None, {}):
            with self.subTest(raw=raw):
                config = convo_config.parse(raw)
                self.assert_defaults(config)
                self.assertIn("overrides=none", convo_config.log_line(config, None))

    async def test_c02_valid_values_are_trimmed_applied_and_listed(self) -> None:
        raw = {
            "prompt_version": " V21 ",
            "stt_keyterms": " ON ",
            "stt_numerals": "on",
            "stt_region": " EU ",
            "greeting_tags": "On",
        }
        config = convo_config.parse(raw)
        self.assertEqual(config.prompt_version, "v21")
        self.assertTrue(config.stt_keyterms)
        self.assertTrue(config.stt_numerals)
        self.assertEqual(config.stt_region, "eu")
        self.assertTrue(config.greeting_tags)
        self.assertEqual(config.overrides, tuple(raw))

    async def test_c03_invalid_values_warn_once_and_fall_back_without_echoing_long_input(self) -> None:
        cases = {
            "prompt_version": ("v3", "V2.1", "", "x" * 500),
            "stt_keyterms": ("yes", ""),
            "stt_numerals": ("yes", ""),
            "stt_region": ("EU-west", ""),
            "greeting_tags": ("yes", ""),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value[:20]), patch.object(
                    convo_config.logger, "warning"
                ) as warning:
                    config = convo_config.parse({field: value})
                    self.assertEqual(getattr(config, field), DEFAULTS[field])
                    self.assertEqual(config.overrides, ())
                    warning.assert_called_once()
                    rendered = " ".join(str(part) for part in warning.call_args.args)
                    self.assertIn(field, rendered)
                    if len(value) > 100:
                        self.assertNotIn(value, rendered)

    async def test_c04_unknown_field_warns_and_changes_nothing(self) -> None:
        with patch.object(convo_config.logger, "warning") as warning:
            config = convo_config.parse({"stt_keyterm": "on"})
        self.assert_defaults(config)
        warning.assert_called_once()
        self.assertIn("stt_keyterm", str(warning.call_args.args[0]))

        long_field = "private-" + "x" * 500
        with patch.object(convo_config.logger, "warning") as warning:
            config = convo_config.parse({long_field: "on"})
        self.assert_defaults(config)
        rendered = str(warning.call_args.args[0])
        self.assertLess(len(rendered), 150)
        self.assertNotIn(long_field, rendered)

    async def test_c05_read_failures_are_bounded_warn_with_class_only_and_close(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            convo_config.logger, "warning"
        ) as warning:
            started = time.monotonic()
            config = await convo_config.read_convo_config()
            self.assertLess(time.monotonic() - started, 1.0)
        self.assert_defaults(config)
        self.assertIn("overrides=unavailable", convo_config.log_line(config, None))
        warning.assert_called_once()
        self.assertIn("RuntimeError", str(warning.call_args.args[0]))

        for client in (
            FakeRedis(error=ConnectionError("contains-private-detail")),
            FakeRedis(delay=5.0),
        ):
            with self.subTest(client=client), patch.dict(
                os.environ, {"REDIS_URL": "redis://test-only"}, clear=True
            ), patch.object(
                convo_config.redis, "from_url", return_value=client
            ), patch.object(
                convo_config.logger, "warning"
            ) as warning:
                started = time.monotonic()
                config = await convo_config.read_convo_config()
                elapsed = time.monotonic() - started
            self.assertLess(elapsed, 1.0)
            self.assert_defaults(config)
            self.assertIn("overrides=unavailable", convo_config.log_line(config, None))
            self.assertTrue(client.closed)
            warning.assert_called_once()
            rendered = " ".join(str(part) for part in warning.call_args.args)
            self.assertRegex(rendered, r"ConnectionError|TimeoutError")
            self.assertNotIn("contains-private-detail", rendered)
            self.assertNotIn("redis://test-only", rendered)

        junk_client = FakeRedis(result="not-a-hash")
        with patch.dict(
            os.environ, {"REDIS_URL": "redis://test-only"}, clear=True
        ), patch.object(
            convo_config.redis, "from_url", return_value=junk_client
        ), patch.object(convo_config.logger, "warning") as warning:
            config = await convo_config.read_convo_config()
        self.assert_defaults(config)
        self.assertIn("overrides=unavailable", convo_config.log_line(config, None))
        warning.assert_called_once()

    async def test_c06_log_line_shape_has_no_url_or_key_value(self) -> None:
        secret_url = "redis://user:password@example.invalid/0"
        secret_key = "sk-test-value-that-must-not-appear"
        with patch.dict(
            os.environ,
            {"REDIS_URL": secret_url, "OPENAI_API_KEY": secret_key},
            clear=True,
        ):
            config = convo_config.parse(
                {"prompt_version": "v21", "stt_keyterms": "on"}, read_ms=17
            )
            line = convo_config.log_line(config, "abcdef")
        self.assertRegex(
            line,
            r"^convo config: conn=(?:[0-9a-f]{6}|-) prompt_version=\S+ "
            r"stt_keyterms=\S+ stt_numerals=\S+ stt_region=\S+ "
            r"greeting_tags=\S+ read_ms=\d+ overrides=\S+$",
        )
        self.assertNotIn(secret_url, line)
        self.assertNotIn(secret_key, line)

        output = io.StringIO()
        with patch.dict(
            os.environ,
            {"REDIS_URL": secret_url, "OPENAI_API_KEY": secret_key},
            clear=True,
        ):
            log_scrub.configure_logging("INFO", stream=output)
            try:
                convo_config.logger.info(line)
            finally:
                log_scrub.configure_logging("DEBUG")
        scrubbed = output.getvalue()
        self.assertIn("convo config:", scrubbed)
        self.assertNotIn(secret_url, scrubbed)
        self.assertNotIn(secret_key, scrubbed)

    async def test_c07_tags_are_allowed_only_for_v4_models(self) -> None:
        self.assertTrue(convo_config.tags_allowed("eleven_v4_turbo"))
        for model in ("eleven_flash_v2_5", "eleven_turbo_v2", None, ""):
            with self.subTest(model=model):
                self.assertFalse(convo_config.tags_allowed(model))

    async def test_g01_and_k04_no_hash_preserves_today_field_for_field(self) -> None:
        redis_client = FakeRedis(result={})
        with patch.dict(
            os.environ, {"REDIS_URL": "redis://test-only"}, clear=True
        ), patch.object(
            convo_config.redis, "from_url", return_value=redis_client
        ), patch.object(
            convo_config.logger, "warning"
        ) as warning:
            default_config = await convo_config.read_convo_config()
        warning.assert_not_called()
        self.assertTrue(redis_client.closed)
        self.assert_defaults(default_config)

        result = await run_wired_bot(default_config)
        plain = bot.build_greeting(bot.LEAD_SOURCE_DEMO_FORM, "Test Heights")
        self.assertEqual(result.frame.text, plain)
        kwargs = result.stt.call_args.kwargs
        self.assertNotIn("base_url", kwargs)
        settings = kwargs["settings"]
        self.assertEqual(settings.model, "nova-3")
        self.assertEqual(str(settings.language), "en-IN")
        self.assertTrue(settings.smart_format)
        self.assertTrue(settings.interim_results)
        self.assertEqual(settings.endpointing, 300)
        self.assertFalse(is_given(settings.keyterm))
        self.assertFalse(is_given(settings.numerals))
        self.assertEqual(kwargs["region"], "global")

    async def test_g02_tags_on_flash_warns_blocks_and_queues_plain_greeting(self) -> None:
        config = convo_config.parse({"greeting_tags": "on"})
        result = await run_wired_bot(config, active_model="eleven_flash_v2_5")
        self.assertEqual(
            result.frame.text,
            bot.build_greeting(bot.LEAD_SOURCE_DEMO_FORM, "Test Heights"),
        )
        result.warning.assert_called_once_with(
            "greeting_tags is on but the voice model is not v4; using the plain greeting"
        )
        info_lines = [str(call.args[0]) for call in result.info.call_args_list]
        self.assertTrue(any("greeting_tags=blocked" in line for line in info_lines))
        self.assertNotIn("[", result.frame.text)
        result.tag_guard.assert_called_once_with("eleven_flash_v2_5")

    async def test_g03_tags_allowed_queues_tagged_greeting_but_plain_context(self) -> None:
        config = convo_config.parse({"greeting_tags": "on"})
        result = await run_wired_bot(config, active_model="eleven_v4_turbo")
        self.assertIn("[warm]", result.frame.text)
        messages = result.context.call_args.kwargs["messages"]
        self.assertNotRegex(messages[-1]["content"], r"\[[^]]+\]")
        self.assertNotEqual(result.frame.text, messages[-1]["content"])
        result.tag_guard.assert_called_once_with("eleven_v4_turbo")

    async def test_g04_prompt_variant_is_passed_and_logged(self) -> None:
        for version in ("v2", "v21"):
            with self.subTest(version=version):
                result = await run_wired_bot(
                    convo_config.parse({"prompt_version": version})
                )
                self.assertEqual(result.messages.call_args.kwargs["version"], version)
                lines = [str(call.args[0]) for call in result.info.call_args_list]
                prompt_line = next(line for line in lines if line.startswith("prompt v2:"))
                self.assertRegex(
                    prompt_line,
                    r"^prompt v2: chars=\d+ lead_source=demo_form "
                    r"disclosure_mode=\S+ company=\S+ version=\S+$",
                )
                self.assertTrue(prompt_line.endswith(f"version={version}"))

    async def test_g05_exactly_one_config_line_is_logged_per_call(self) -> None:
        result = await run_wired_bot(convo_config.ConvoConfig())
        lines = [str(call.args[0]) for call in result.info.call_args_list]
        self.assertEqual(sum(line.startswith("convo config:") for line in lines), 1)


if __name__ == "__main__":
    unittest.main()
