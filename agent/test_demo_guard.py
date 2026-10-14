import asyncio
import importlib
import io
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class FakeRedis:
    """Small decode_responses=True Redis fake for demo-guard tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, str]] = []

    async def get(self, key: str):
        self.calls.append(("get", key))
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex=None, nx=False):
        self.calls.append(("set", key))
        if nx and key in self.values:
            return None
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str):
        self.calls.append(("incr", key))
        self.values[key] = str(int(self.values.get(key, "0")) + 1)
        return int(self.values[key])

    async def decr(self, key: str):
        self.calls.append(("decr", key))
        self.values[key] = str(int(self.values.get(key, "0")) - 1)
        return int(self.values[key])

    async def eval(self, script: str, numkeys: int, key: str):
        self.calls.append(("eval", key))
        value = self.values.get(key)
        if value is None or int(value) <= 0:
            return 0
        self.values[key] = str(int(value) - 1)
        return int(self.values[key])

    async def ttl(self, key: str):
        self.calls.append(("ttl", key))
        if key not in self.values:
            return -2
        return self.ttls.get(key, -1)

    async def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
            self.ttls.pop(key, None)
        return len(keys)

    async def hgetall(self, key: str):
        self.calls.append(("hgetall", key))
        return self.hashes.get(key, {}).copy()

    async def hset(self, key: str, mapping: dict[str, str]):
        self.hashes.setdefault(key, {}).update(mapping)


class UnavailableRedis(FakeRedis):
    async def _fail(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    get = set = incr = decr = eval = delete = hgetall = hset = ttl = _fail


class HangingRedis(UnavailableRedis):
    async def _fail(self, *args, **kwargs):
        await asyncio.Event().wait()

    get = set = incr = decr = eval = delete = hgetall = hset = ttl = _fail


class ConfigUnavailableRedis(FakeRedis):
    async def hgetall(self, key: str):
        raise ConnectionError("configuration unavailable")


class FakeResponse:
    def __init__(self, status: int, payload=None) -> None:
        self.status = status
        self._payload = payload if payload is not None else []

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeSession:
    def __init__(self, project_response=None, consent_status: int = 201) -> None:
        self.project_response = project_response or FakeResponse(
            200, [{"id": "project-1", "tenant_id": "tenant-1"}]
        )
        self.consent_status = consent_status
        self.calls: list[tuple[str, str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self.project_response

    def post(self, url: str, **kwargs):
        self.calls.append(("post", url, kwargs))
        return FakeResponse(self.consent_status)


class DemoGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from agent import demo_guard

        self.guard = demo_guard

    async def test_phone_validation_refuses_every_non_indian_mobile_shape(self) -> None:
        self.assertTrue(self.guard.validate_phone("+919876543210"))
        for value in [
            "+14155550100",
            "+911234567890",
            "+91987654321",
            "9876543210",
            None,
            919876543210,
            "+9198765432100",
        ]:
            with self.subTest(value=value):
                self.assertFalse(self.guard.validate_phone(value))

    async def test_ip_parsing_uses_real_ip_and_buckets_v6_by_64(self) -> None:
        parsed = self.guard.parse_client_ip("::ffff:198.51.100.4")
        self.assertEqual(parsed.address, "198.51.100.4")
        self.assertEqual(parsed.bucket, "198.51.100.4")

        first = self.guard.parse_client_ip("2401:4900:1234:5678::1")
        second = self.guard.parse_client_ip("2401:4900:1234:5678:ffff::2")
        self.assertEqual(first.bucket, "2401:4900:1234:5678::/64")
        self.assertEqual(first.bucket, second.bucket)
        self.assertEqual(first.address, "2401:4900:1234:5678::1")

        for raw in [None, "", "garbage", "fe80::1%eth0"]:
            with self.subTest(raw=raw):
                self.assertEqual(self.guard.parse_client_ip(raw).address, None)
                self.assertEqual(self.guard.parse_client_ip(raw).bucket, "unknown")

    async def test_kill_switch_and_config_are_redis_backed_and_safe(self) -> None:
        redis = FakeRedis()
        self.assertFalse(await self.guard.kill_switch_on(redis))
        redis.values["demo:kill"] = "1"
        self.assertTrue(await self.guard.kill_switch_on(redis))

        redis.hashes["demo:config"] = {
            "phone_limit": "1",
            "ip_limit": "abc",
            "global_limit": "0",
            "window_seconds": "-3",
        }
        config = await self.guard.read_config(redis)
        self.assertEqual(config.phone_limit, 1)
        self.assertEqual(config.ip_limit, self.guard.DEFAULT_CONFIG.ip_limit)
        self.assertEqual(config.global_limit, self.guard.DEFAULT_CONFIG.global_limit)
        self.assertEqual(config.window_seconds, self.guard.DEFAULT_CONFIG.window_seconds)

    async def test_reservation_enforces_cooldowns_caps_ttls_and_refunds(self) -> None:
        redis = FakeRedis()
        config = self.guard.DemoConfig(
            phone_limit=3,
            ip_limit=10,
            global_limit=50,
            phone_cooldown_seconds=180,
            ip_cooldown_seconds=30,
            window_seconds=86400,
        )
        reservation = await self.guard.reserve(redis, "+919876543210", "198.51.100.4", config)
        for key in reservation.counter_keys:
            self.assertIn(key, redis.ttls)

        with self.assertRaises(self.guard.LimitExceeded) as raised:
            await self.guard.reserve(redis, "+919876543210", "198.51.100.4", config)
        self.assertEqual(raised.exception.limit, "cooldown")
        self.assertEqual(redis.values[reservation.counter_keys[0]], "1")

        await self.guard.refund(redis, reservation)
        self.assertEqual([redis.values[key] for key in reservation.counter_keys], ["0", "0", "0"])
        self.assertIn("demo:cd:phone:+919876543210", redis.values)
        self.assertIn("demo:cd:ip:198.51.100.4", redis.values)

        await redis.delete("demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4")
        for _ in range(3):
            await self.guard.reserve(redis, "+919876543210", "198.51.100.4", config)
            await redis.delete("demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4")
        with self.assertRaises(self.guard.LimitExceeded) as raised:
            await self.guard.reserve(redis, "+919876543210", "198.51.100.4", config)
        self.assertEqual(raised.exception.limit, "phone")

    async def test_tenant_lookup_is_project_scoped_cached_and_never_reads_tenants_directly(self) -> None:
        session = FakeSession()
        state = SimpleNamespace()
        with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=False):
            tenant_id = await self.guard.resolve_tenant_id(state, session, "nxlyr-demo")
            self.assertEqual(tenant_id, "tenant-1")
            self.assertEqual(await self.guard.resolve_tenant_id(state, session, "nxlyr-demo"), "tenant-1")

        self.assertEqual(len(session.calls), 1)
        method, url, kwargs = session.calls[0]
        self.assertEqual(method, "get")
        self.assertTrue(url.endswith("/rest/v1/projects"))
        self.assertEqual(kwargs["params"], {
            "select": "id,tenant_id,tenants!inner(slug)",
            "tenants.slug": "eq.nxlyr-demo",
            "limit": "1",
        })
        self.assertNotIn("*", str(kwargs))
        self.assertNotIn("api_key", str(kwargs))

    async def test_missing_or_bad_tenant_response_fails_closed(self) -> None:
        cases = [
            FakeResponse(200, []),
            FakeResponse(200, [{"tenant_id": None}]),
            FakeResponse(400, []),
            FakeResponse(500, []),
        ]
        for response in cases:
            with self.subTest(status=response.status, payload=response._payload):
                with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=False):
                    with self.assertRaises(self.guard.ConsentStorageError):
                        await self.guard.resolve_tenant_id(SimpleNamespace(), FakeSession(response), "nxlyr-demo")

    async def test_consent_payload_is_server_held_and_minimises_header_data(self) -> None:
        session = FakeSession()
        headers = {
            "origin": "https://nxlyr.vercel.app",
            "referer": "https://attacker.example/a?x=1",
            "user-agent": "x" * 700,
        }
        with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=False):
            await self.guard.record_consent(
                session,
                tenant_id="tenant-1",
                phone_number="+919876543210",
                consent_version="v1",
                headers=headers,
                ip_address="198.51.100.4",
            )
        _, url, kwargs = session.calls[0]
        self.assertTrue(url.endswith("/rest/v1/consents"))
        payload = kwargs["json"]
        self.assertEqual(payload["action"], "granted")
        self.assertEqual(payload["source"], "web_form")
        self.assertEqual(payload["consent_text"], self.guard.CONSENT_TEXTS["v1"])
        self.assertEqual(payload["consent_text_version"], "v1")
        self.assertEqual(payload["page_url"], "https://nxlyr.vercel.app")
        self.assertEqual(len(payload["user_agent"]), 512)
        self.assertNotIn("lead_id", payload)
        self.assertNotIn("occurred_at", payload)
        self.assertNotIn("created_at", payload)

    async def test_referer_falls_back_to_origin_only(self) -> None:
        self.assertEqual(
            self.guard.page_url_from_headers({"origin": "https://nxlyr.vercel.app/a/b?x=1"}),
            "https://nxlyr.vercel.app",
        )
        self.assertEqual(
            self.guard.page_url_from_headers({"referer": "https://nxlyr.vercel.app/a/b?x=1"}),
            "https://nxlyr.vercel.app",
        )
        for headers in [
            {"origin": "null"},
            {"origin": "not a url"},
            {"referer": "not a url"},
            {"origin": f"https://{'x' * 2048}.example"},
            {"referer": f"https://{'x' * 2048}.example/a?b=1"},
        ]:
            with self.subTest(headers=headers):
                self.assertIsNone(self.guard.page_url_from_headers(headers))

    async def test_refund_never_creates_negative_or_ttl_less_counters(self) -> None:
        redis = FakeRedis()
        reservation = self.guard.Reservation(("expired", "zero", "one"))
        redis.values["zero"] = "0"
        redis.ttls["zero"] = 10
        redis.values["one"] = "1"
        redis.ttls["one"] = 10

        await self.guard.refund(redis, reservation)

        self.assertNotIn("expired", redis.values)
        self.assertEqual(redis.values["zero"], "0")
        self.assertEqual(redis.values["one"], "0")
        self.assertEqual(redis.ttls["zero"], 10)
        self.assertEqual(redis.ttls["one"], 10)

    async def test_ip_cooldown_refusal_does_not_set_phone_cooldown_and_uses_remaining_ttl(self) -> None:
        redis = FakeRedis()
        redis.values["demo:cd:ip:198.51.100.4"] = "1"
        redis.ttls["demo:cd:ip:198.51.100.4"] = 7
        config = self.guard.DemoConfig()

        with self.assertRaises(self.guard.LimitExceeded) as raised:
            await self.guard.reserve(redis, "+919876543210", "198.51.100.4", config)

        self.assertEqual(raised.exception.limit, "cooldown")
        self.assertEqual(raised.exception.retry_after, 7)
        self.assertNotIn("demo:cd:phone:+919876543210", redis.values)

    async def test_unavailable_and_hanging_redis_raise_guard_unavailable(self) -> None:
        for redis in [UnavailableRedis(), HangingRedis()]:
            with self.subTest(redis=type(redis).__name__):
                with self.assertRaises(self.guard.GuardUnavailable):
                    await self.guard.kill_switch_on(redis)

    async def test_config_read_failure_is_not_treated_as_default_config(self) -> None:
        with self.assertRaises(self.guard.GuardUnavailable):
            await self.guard.read_config(ConfigUnavailableRedis())


def import_server_without_dotenv():
    agent_directory = str(Path(__file__).parent)
    if agent_directory not in sys.path:
        sys.path.insert(0, agent_directory)
    with patch("dotenv.load_dotenv"):
        return importlib.import_module("server")


class DemoCallEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, redis, session, *, phone="+919876543210", version=..., headers=None):
        server = import_server_without_dotenv()
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(redis=redis, session=session)),
            headers=headers or {"x-real-ip": "198.51.100.4"},
        )
        body_fields = {"phone_number": phone}
        if version is not ...:
            body_fields["consent_text_version"] = version
        body = server.DemoCallRequest(**body_fields)
        return server, request, body

    async def test_success_records_consent_before_dial_and_writes_f01_binding(self) -> None:
        redis = FakeRedis()
        session = FakeSession()
        server, request, body = await self.call(
            redis,
            session,
            headers={
                "x-real-ip": "198.51.100.4",
                "x-forwarded-for": "203.0.113.9",
                "origin": "https://nxlyr.vercel.app",
            },
        )
        exotel_response = server.JSONResponse(
            status_code=200, content={"status": "success", "call_sid": "call-1"}
        )
        with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=False), patch.object(
            server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)
        ) as trigger:
            response = await server.request_demo_call(request, body)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([call[0] for call in session.calls], ["get", "post"])
        self.assertEqual(session.calls[1][2]["json"]["ip_address"], "198.51.100.4")
        trigger.assert_awaited_once_with(request, "+919876543210")
        self.assertIn("ws_bind:call-1", redis.values)
        self.assertEqual(redis.ttls["ws_bind:call-1"], 120)

    async def test_kill_phone_and_unknown_version_refuse_before_storage_or_dial(self) -> None:
        cases = [
            ("kill", "+919876543210", "v1", 503, "demo_disabled"),
            ("phone", "+14155550100", "v1", 400, "invalid_phone_number"),
            ("version", "+919876543210", "v2", 400, "consent_version_unknown"),
            ("null-version", "+919876543210", None, 400, "consent_version_unknown"),
        ]
        for kind, phone, version, expected_status, expected_type in cases:
            with self.subTest(kind=kind):
                redis = FakeRedis()
                if kind == "kill":
                    redis.values["demo:kill"] = "1"
                session = FakeSession()
                server, request, body = await self.call(redis, session, phone=phone, version=version)
                with patch.object(server, "trigger_exotel_call", new=AsyncMock()) as trigger:
                    response = await server.request_demo_call(request, body)
                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(__import__("json").loads(response.body)["type"], expected_type)
                self.assertEqual(session.calls, [])
                trigger.assert_not_awaited()

    async def test_storage_and_exotel_failures_refund_counters_but_keep_cooldowns(self) -> None:
        for session, response in [
            (FakeSession(project_response=FakeResponse(500)), None),
            (FakeSession(), None),
        ]:
            with self.subTest(storage_failure=session.project_response.status == 500):
                redis = FakeRedis()
                server, request, body = await self.call(redis, session)
                exotel_response = server.JSONResponse(status_code=500, content={"error": "broken"})
                with patch.dict(os.environ, {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"}, clear=False), patch.object(
                    server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)
                ) as trigger:
                    result = await server.request_demo_call(request, body)
                if session.project_response.status == 500:
                    self.assertEqual(result.status_code, 500)
                    self.assertEqual(__import__("json").loads(result.body)["type"], "consent_storage_failed")
                    trigger.assert_not_awaited()
                else:
                    self.assertEqual(result.status_code, 502)
                    trigger.assert_awaited_once()
                counter_keys = [key for key in redis.values if key.startswith("demo:rate:")]
                self.assertEqual([redis.values[key] for key in counter_keys], ["0", "0", "0"])
                self.assertIn("demo:cd:phone:+919876543210", redis.values)
                self.assertIn("demo:cd:ip:198.51.100.4", redis.values)

    async def test_unavailable_redis_prevents_all_other_side_effects(self) -> None:
        redis = UnavailableRedis()
        session = FakeSession()
        server, request, body = await self.call(redis, session)
        with patch.object(server, "trigger_exotel_call", new=AsyncMock()) as trigger:
            response = await server.request_demo_call(request, body)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(__import__("json").loads(response.body)["type"], "rate_limit_unavailable")
        self.assertEqual(session.calls, [])
        trigger.assert_not_awaited()
        self.assertFalse(any(key.startswith("ws_bind:") for key in redis.values))

    async def test_endpoint_caps_return_documented_429_without_refunds(self) -> None:
        server = import_server_without_dotenv()
        exotel_response = server.JSONResponse(
            status_code=200, content={"status": "success", "call_sid": "call-1"}
        )

        async def submit(redis, session, phone, ip):
            _, request, body = await self.call(
                redis, session, phone=phone, headers={"x-real-ip": ip}
            )
            return await server.request_demo_call(request, body)

        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"},
            clear=False,
        ), patch.object(server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)):
            ip_redis = FakeRedis()
            ip_redis.hashes["demo:config"] = {
                "phone_limit": "100",
                "ip_limit": "1",
                "global_limit": "100",
            }
            ip_session = FakeSession()
            self.assertEqual(
                (await submit(ip_redis, ip_session, "+919876543210", "198.51.100.4")).status_code,
                200,
            )
            await ip_redis.delete("demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4")
            ip_limited = await submit(ip_redis, ip_session, "+919876543210", "198.51.100.4")

            self.assertEqual(ip_limited.status_code, 429)
            self.assertEqual(json.loads(ip_limited.body), {
                "status": "error",
                "type": "rate_limited",
                "error": "rate_limit_exceeded",
                "limit": "ip",
                "detail": "This demo-call limit has been reached.",
            })
            self.assertNotIn("retry-after", ip_limited.headers)
            self.assertEqual(ip_redis.values["demo:rate:ip:198.51.100.4"], "2")
            self.assertEqual(len(ip_session.calls), 2)

            global_redis = FakeRedis()
            global_redis.hashes["demo:config"] = {
                "phone_limit": "100",
                "ip_limit": "100",
                "global_limit": "1",
            }
            global_session = FakeSession()
            self.assertEqual(
                (await submit(global_redis, global_session, "+919876543210", "198.51.100.4")).status_code,
                200,
            )
            await global_redis.delete("demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4")
            global_limited = await submit(
                global_redis, global_session, "+919876543211", "198.51.100.5"
            )

        self.assertEqual(global_limited.status_code, 429)
        self.assertEqual(json.loads(global_limited.body)["limit"], "global")
        global_key = next(key for key in global_redis.values if key.startswith("demo:rate:global:"))
        self.assertEqual(global_redis.values[global_key], "2")
        self.assertEqual(len(global_session.calls), 2)

    async def test_endpoint_cooldown_uses_remaining_retry_after_without_refund(self) -> None:
        redis = FakeRedis()
        session = FakeSession()
        server, request, body = await self.call(redis, session)
        exotel_response = server.JSONResponse(
            status_code=200, content={"status": "success", "call_sid": "call-1"}
        )
        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"},
            clear=False,
        ), patch.object(server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)):
            self.assertEqual((await server.request_demo_call(request, body)).status_code, 200)
            await redis.delete("demo:cd:ip:198.51.100.4")
            redis.ttls["demo:cd:phone:+919876543210"] = 7
            _, retry_request, retry_body = await self.call(redis, session)
            response = await server.request_demo_call(retry_request, retry_body)

        self.assertEqual(response.status_code, 429)
        self.assertEqual(json.loads(response.body)["limit"], "cooldown")
        self.assertEqual(response.headers["retry-after"], "7")
        self.assertEqual(redis.values["demo:rate:phone:+919876543210"], "1")
        self.assertEqual(len(session.calls), 2)

    async def test_endpoint_config_changes_caps_and_invalid_values_fall_back(self) -> None:
        server = import_server_without_dotenv()
        exotel_response = server.JSONResponse(
            status_code=200, content={"status": "success", "call_sid": "call-1"}
        )

        async def submit(redis, session):
            _, request, body = await self.call(redis, session)
            return await server.request_demo_call(request, body)

        with patch.dict(
            os.environ,
            {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"},
            clear=False,
        ), patch.object(server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)):
            strict_redis = FakeRedis()
            strict_redis.hashes["demo:config"] = {"phone_limit": "1"}
            strict_session = FakeSession()
            self.assertEqual((await submit(strict_redis, strict_session)).status_code, 200)
            await strict_redis.delete("demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4")
            self.assertEqual((await submit(strict_redis, strict_session)).status_code, 429)

            fallback_redis = FakeRedis()
            fallback_redis.hashes["demo:config"] = {"phone_limit": "0"}
            fallback_session = FakeSession()
            for _ in range(3):
                self.assertEqual((await submit(fallback_redis, fallback_session)).status_code, 200)
                await fallback_redis.delete(
                    "demo:cd:phone:+919876543210", "demo:cd:ip:198.51.100.4"
                )
            fallback_response = await submit(fallback_redis, fallback_session)

        self.assertEqual(fallback_response.status_code, 429)
        self.assertEqual(json.loads(fallback_response.body)["limit"], "phone")

    async def test_hung_and_config_failed_redis_have_no_endpoint_side_effects(self) -> None:
        for redis in [HangingRedis(), ConfigUnavailableRedis()]:
            with self.subTest(redis=type(redis).__name__):
                session = FakeSession()
                server, request, body = await self.call(redis, session)
                with patch.object(server, "trigger_exotel_call", new=AsyncMock()) as trigger:
                    response = await asyncio.wait_for(
                        server.request_demo_call(request, body), timeout=2.5
                    )
                self.assertEqual(response.status_code, 500)
                self.assertEqual(json.loads(response.body)["type"], "rate_limit_unavailable")
                self.assertEqual(session.calls, [])
                trigger.assert_not_awaited()
                self.assertFalse(any(key.startswith("ws_bind:") for key in redis.values))

    async def test_failure_logs_exclude_phone_and_ip(self) -> None:
        from loguru import logger

        phone = "+919876543210"
        ip_address = "198.51.100.4"
        captured = io.StringIO()
        sink_id = logger.add(captured, format="{message}", diagnose=True)
        try:
            unavailable_session = FakeSession()
            server, request, body = await self.call(
                UnavailableRedis(), unavailable_session, phone=phone, headers={"x-real-ip": ip_address}
            )
            with patch.object(server, "trigger_exotel_call", new=AsyncMock()):
                await server.request_demo_call(request, body)

            storage_session = FakeSession(project_response=FakeResponse(500))
            server, request, body = await self.call(
                FakeRedis(), storage_session, phone=phone, headers={"x-real-ip": ip_address}
            )
            with patch.dict(
                os.environ,
                {"SUPABASE_URL": "https://supabase.example", "SUPABASE_SERVICE_ROLE_KEY": "test-key"},
                clear=False,
            ), patch.object(server, "trigger_exotel_call", new=AsyncMock()):
                await server.request_demo_call(request, body)
        finally:
            logger.remove(sink_id)

        self.assertNotIn(phone, captured.getvalue())
        self.assertNotIn(ip_address, captured.getvalue())


if __name__ == "__main__":
    unittest.main()
