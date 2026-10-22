import ast
import importlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from loguru import logger


AGENT_DIRECTORY = Path(__file__).parent
if str(AGENT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(AGENT_DIRECTORY))


def import_server_without_dotenv():
    with patch("dotenv.load_dotenv"):
        return importlib.import_module("server")


class RaisingContextManager:
    async def __aenter__(self):
        raise RuntimeError("request failed")

    async def __aexit__(self, *args):
        return None


class Response:
    def __init__(self, status, text, payload=None):
        self.status = status
        self._text = text
        self._payload = payload

    async def text(self):
        return self._text

    async def json(self, **kwargs):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class LogHygieneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log_scrub = importlib.import_module("log_scrub")
        self.output = io.StringIO()
        self.log_scrub.configure_logging("DEBUG", stream=self.output)

    def tearDown(self):
        self.log_scrub.configure_logging("DEBUG")

    def text(self):
        return self.output.getvalue()

    def server(self):
        server = import_server_without_dotenv()
        self.log_scrub.configure_logging("DEBUG", stream=self.output)
        return server

    def test_t1_exception_tracebacks_keep_messages_but_not_locals(self):
        secret = "FAKE-SECRET-LOCAL-123456"

        def fail_with_local():
            fake_secret = secret
            raise RuntimeError("expected local failure") if fake_secret else RuntimeError("unexpected")

        try:
            fail_with_local()
        except RuntimeError:
            logger.exception("expected exception")

        output = self.text()
        self.assertNotIn(secret, output)
        self.assertIn("RuntimeError", output)
        self.assertIn("expected local failure", output)

        raw_output = io.StringIO()
        logger.remove()
        logger.add(raw_output, diagnose=True, backtrace=True)
        try:
            fail_with_local()
        except RuntimeError:
            logger.exception("raw exception")
        finally:
            self.log_scrub.configure_logging("DEBUG", stream=self.output)
        self.assertIn(secret, raw_output.getvalue())

    def test_t1c_server_import_installs_one_safe_handler(self):
        secret = "FAKE-SUBPROCESS-SECRET-123456"
        production = """
import io
import os
import sys
from contextlib import redirect_stderr

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: None
sys.path.insert(0, os.getcwd())

output = io.StringIO()
with redirect_stderr(output):
    import server
    from loguru import logger

    handlers = list(logger._core.handlers.values())
    assert len(handlers) == 1
    assert handlers[0]._exception_formatter._diagnose is False

    def fail_with_local():
        fake_secret = os.environ[\"FAKE_API_TOKEN\"]
        raise RuntimeError(\"fresh interpreter failure\") if fake_secret else RuntimeError(\"unexpected\")

    try:
        fail_with_local()
    except RuntimeError:
        logger.exception(\"fresh interpreter exception\")

assert os.environ[\"FAKE_API_TOKEN\"] not in output.getvalue()
assert \"RuntimeError\" in output.getvalue()
print(\"server logging wiring verified\")
"""
        control = """
import io
import os
import sys
from contextlib import redirect_stderr
from loguru import logger

output = io.StringIO()
with redirect_stderr(output):
    logger.remove()
    logger.add(sys.stderr, diagnose=True)

    def fail_with_local():
        fake_secret = os.environ[\"FAKE_API_TOKEN\"]
        raise RuntimeError(\"control failure\") if fake_secret else RuntimeError(\"unexpected\")

    try:
        fail_with_local()
    except RuntimeError:
        logger.exception(\"control exception\")

assert os.environ[\"FAKE_API_TOKEN\"] in output.getvalue()
"""
        environment = {"FAKE_API_TOKEN": secret}
        if sys.platform == "win32":
            environment["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        with tempfile.TemporaryDirectory() as temporary_directory:
            production_script = Path(temporary_directory) / "production_probe.py"
            production_script.write_text(production)
            control_script = Path(temporary_directory) / "control_probe.py"
            control_script.write_text(control)
            result = subprocess.run(
                [sys.executable, str(production_script)],
                cwd=AGENT_DIRECTORY,
                env=environment,
                capture_output=True,
                text=True,
            )
            control_result = subprocess.run(
                [sys.executable, str(control_script)],
                cwd=AGENT_DIRECTORY,
                env=environment,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("server logging wiring verified", result.stdout)
        self.assertEqual(control_result.returncode, 0, control_result.stdout + control_result.stderr)

    async def test_t1b_real_exception_sites_scrub_fake_credentials_and_phone(self):
        server = self.server()
        phone = "+919876543210"
        fake_values = {
            "EXOTEL_SID": "FAKE-SID-12345678",
            "EXOTEL_API_KEY": "FAKE-EXOTEL-KEY-12345678",
            "EXOTEL_API_TOKEN": "FAKE-EXOTEL-TOKEN-12345678",
            "EXOTEL_PHONE_NUMBER": "+919812345678",
            "EXOTEL_APP_ID": "FAKE-APP-12345678",
            "SUPABASE_URL": "https://supabase.example",
            "SUPABASE_SERVICE_ROLE_KEY": "FAKE-SUPABASE-KEY-12345678",
        }
        session = SimpleNamespace(post=lambda *args, **kwargs: RaisingContextManager())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session=session)))
        telegram_request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    session=session,
                    telegram_bot_token="FAKE-TELEGRAM-TOKEN-12345678",
                    telegram_chat_id="12345678",
                )
            )
        )

        with patch.dict(os.environ, fake_values, clear=False):
            await server.trigger_exotel_call(request, phone)
            with self.assertRaises(RuntimeError):
                await server.store_contact_submission(
                    request, name="Person", email="person@example.test", company=None
                )
            await server.notify_contact_submission_via_telegram(
                telegram_request, name="Person", email="person@example.test", company=None
            )

        output = self.text()
        for value in [
            fake_values["EXOTEL_API_KEY"],
            fake_values["EXOTEL_API_TOKEN"],
            fake_values["SUPABASE_SERVICE_ROLE_KEY"],
            "FAKE-TELEGRAM-TOKEN-12345678",
            phone,
        ]:
            self.assertNotIn(value, output)
        self.assertIn("Failed to connect to Exotel API", output)
        self.assertIn("Unable to store contact submission in Supabase", output)
        self.assertIn("Telegram contact notification failed", output)
        self.assertNotIn("└ BasicAuth(", output)
        self.assertNotIn("'Authorization':", output)
        self.assertNotIn("└ {'name': 'Person'", output)

    def test_t2_phone_numbers_are_masked_without_masking_safe_identifiers(self):
        phones = ["+919876543210", "919876543210", "09876543210", "9876543210"]
        text = " ".join(phones) + " Parsed - Type: exotel, Data: from='09876543210' to='+919876543210'"
        text += " sid=0123456789abcdef0123456789abcdef ts=1730000000123 latency=1234.5ms call_sid='abc1234567890def'"
        scrubbed = self.log_scrub.scrub(text)
        self.assertIn("****3210", scrubbed)
        self.assertNotIn("987654", scrubbed)
        self.assertNotIn("543210", scrubbed)
        safe_identifiers = " ".join([
            "0123456789abcdef0123456789abcdef",
            "1730000000123",
            "1234.5ms",
            "abc1234567890def",
            "Task-12",
            "disk-usage",
            "robot1:abc",
        ])
        for value in safe_identifiers.split():
            self.assertIn(value, self.log_scrub.scrub(safe_identifiers))

        logger.info("+919876543210")
        try:
            raise RuntimeError("call from 9876543210 failed")
        except RuntimeError:
            logger.exception("phone failure")
        self.assertIn("****3210", self.text())
        self.assertNotIn("987654", self.text())

    async def test_t3_redis_urls_are_removed_from_call_sites_and_messages(self):
        server = self.server()
        tools = importlib.import_module("tools")
        redis_url = "redis://:S3CRETPW@redis-host:6379/0"

        class RedisClient:
            async def ping(self):
                return True

        with patch.dict(os.environ, {"REDIS_URL": redis_url}, clear=False), patch(
            "redis.asyncio.from_url", return_value=RedisClient()
        ):
            self.assertIsNotNone(await tools.make_redis_client())

        class BrokenRedisClient:
            async def ping(self):
                raise RuntimeError("Redis URL must specify one of the following schemes (redis://, rediss://, unix://)")

            async def aclose(self):
                return None

        with patch.dict(os.environ, {"REDIS_URL": redis_url}, clear=False), patch(
            "redis.asyncio.from_url", return_value=BrokenRedisClient()
        ):
            self.assertIsNone(await tools.make_redis_client())
            request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=None)))
            try:
                await server.get_demo_redis_client(request)
            except RuntimeError:
                logger.exception("demo redis failure")

        logger.error("Redis URL must specify one of the following schemes (redis://, rediss://, unix://)")
        output = self.text()
        self.assertNotIn("redis://", output)
        self.assertNotIn("S3CRETPW", output)
        self.assertIn("Redis connected", output)
        self.assertIn("Could not connect to Redis", output)

    async def test_t4_exotel_failure_body_is_not_logged_and_response_is_unchanged(self):
        server = self.server()
        marker = "FAKE-EXOTEL-BODY-MARKER"
        body = f"{marker} +919876543210"
        response = Response(400, body)
        session = SimpleNamespace(post=lambda *args, **kwargs: response)
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(session=session)))
        env = {
            "EXOTEL_SID": "FAKE-SID-12345678",
            "EXOTEL_API_KEY": "FAKE-EXOTEL-KEY-12345678",
            "EXOTEL_API_TOKEN": "FAKE-EXOTEL-TOKEN-12345678",
            "EXOTEL_PHONE_NUMBER": "+919812345678",
            "EXOTEL_APP_ID": "FAKE-APP-12345678",
        }
        with patch.dict(os.environ, env, clear=False):
            result = await server.trigger_exotel_call(request, "+919876543210")

        self.assertEqual(result.status_code, 400)
        self.assertEqual(json.loads(result.body)["detail"], body)
        self.assertNotIn(marker, self.text())
        self.assertNotIn("9876543210", self.text())
        self.assertIn("status 400", self.text())

    def test_t5_prompt_debug_is_dropped_but_other_records_survive(self):
        self.assertIsNotNone(importlib.util.find_spec("pipecat.services.openai.base_llm"))
        namespace = {"logger": logger}
        exec(
            compile("logger.debug('PROMPT-MARKER'); logger.warning('WARNING-MARKER')", "pipecat_base_llm.py", "exec"),
            {**namespace, "__name__": "pipecat.services.openai.base_llm"},
        )
        logger.debug("OTHER-DEBUG-MARKER")
        output = self.text()
        self.assertNotIn("PROMPT-MARKER", output)
        self.assertIn("WARNING-MARKER", output)
        self.assertIn("OTHER-DEBUG-MARKER", output)

    def test_t6_exception_messages_and_secret_shapes_are_scrubbed(self):
        token = "FAKE-API-TOKEN-12345678"
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3OCJ9.signaturepart"
        telegram = "bot123456:ABCDEFghijklmnopqrstuvwxyz_123456"
        with patch.dict(os.environ, {"FAKE_API_TOKEN": token}, clear=False):
            try:
                raise RuntimeError(f"tokens: {token} {jwt} {telegram}")
            except RuntimeError:
                logger.exception("secret failure")
        output = self.text()
        for value in [token, jwt, telegram]:
            self.assertNotIn(value, output)

    def test_t7_scrubber_failure_writes_only_a_safe_placeholder(self):
        stderr = io.StringIO()
        with patch.object(self.log_scrub, "scrub", side_effect=RuntimeError("broken")), redirect_stderr(stderr):
            logger.error("UNSCRUBBED-MARKER")
        self.assertNotIn("UNSCRUBBED-MARKER", self.text())
        self.assertNotIn("UNSCRUBBED-MARKER", stderr.getvalue())
        self.assertIn("[log scrubber failed]", self.text())

    def test_t7b_failing_stream_cannot_emit_raw_record(self):
        class FailingStream:
            def write(self, text):
                raise OSError("stream unavailable")

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            self.log_scrub.configure_logging("DEBUG", stream=FailingStream())
            logger.error("UNSCRUBBED-MARKER +919876543210")
        self.assertNotIn("UNSCRUBBED-MARKER", stderr.getvalue())
        self.assertNotIn("9876543210", stderr.getvalue())

    def test_t8_source_does_not_log_sensitive_locals_and_uses_configure_logging(self):
        forbidden = {"redis_url", "resp_text", "api_key", "api_token", "auth", "bot_token", "supabase_key", "headers"}
        excluded = {
            line.strip()
            for line in (AGENT_DIRECTORY / ".dockerignore").read_text().splitlines()
            if line.strip().endswith(".py")
        }
        for source_path in sorted(AGENT_DIRECTORY.glob("*.py")):
            if source_path.name in excluded:
                continue
            filename = source_path.name
            tree = ast.parse(source_path.read_text())
            for call in [node for node in ast.walk(tree) if isinstance(node, ast.Call)]:
                if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name):
                    continue
                if call.func.value.id != "logger":
                    continue
                names = {node.id for argument in call.args for node in ast.walk(argument) if isinstance(node, ast.Name)}
                names |= {node.id for keyword in call.keywords for node in ast.walk(keyword.value) if isinstance(node, ast.Name)}
                self.assertFalse(names & forbidden, f"{filename}:{call.lineno} logs {names & forbidden}")
                if call.func.attr == "add":
                    self.assertEqual(filename, "log_scrub.py", f"{filename}:{call.lineno} adds a logger handler")
        bot_source = (AGENT_DIRECTORY / "bot.py").read_text()
        self.assertIn("configure_logging(", bot_source)

    def test_t10_empty_and_missing_levels_default_to_debug(self):
        for level in ["", None]:
            output = io.StringIO()
            self.log_scrub.configure_logging(level, stream=output)
            logger.debug("debug survives")
            self.assertIn("debug survives", output.getvalue())
        self.log_scrub.configure_logging("DEBUG", stream=self.output)


if __name__ == "__main__":
    unittest.main()
