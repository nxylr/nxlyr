import asyncio
import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.ws_auth import (
    WS_AUTH_TTL_SECONDS,
    AdmissionCounter,
    ReplayWebSocket,
    StartMessageError,
    admission_session,
    authorize_websocket,
    issue_binding,
    read_start_handshake,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int) -> None:
        self.values[key] = value
        self.last_ttl = ex

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)


class UnavailableRedis:
    async def getdel(self, key: str) -> None:
        raise ConnectionError("redis unavailable")


class FakeWebSocket:
    def __init__(self, messages: list[object], *, delay: float = 0) -> None:
        self.messages = iter(messages)
        self.delay = delay

    async def receive(self) -> dict[str, object]:
        if self.delay:
            await asyncio.sleep(self.delay)
        message = next(self.messages)
        if isinstance(message, Exception):
            raise message
        if isinstance(message, dict):
            return message
        return {"type": "websocket.receive", "text": message}

    async def receive_text(self) -> str:
        message = await self.receive()
        text = message.get("text")
        if not isinstance(text, str):
            raise RuntimeError("Expected WebSocket text frame")
        return text


class FakeEndpointWebSocket(FakeWebSocket):
    def __init__(self, messages: list[str], redis: FakeRedis) -> None:
        super().__init__(messages)
        self.app = SimpleNamespace(state=SimpleNamespace(redis=redis))
        self.close_codes: list[int | None] = []

    async def accept(self) -> None:
        return None

    async def close(self, code: int | None = None) -> None:
        self.close_codes.append(code)


def start_message(call_sid: str) -> str:
    return json.dumps({"event": "start", "start": {"call_sid": call_sid}})


def import_server_without_dotenv():
    agent_directory = str(Path(__file__).parent)
    if agent_directory not in sys.path:
        sys.path.insert(0, agent_directory)
    with patch("dotenv.load_dotenv"):
        return importlib.import_module("server")


class WsAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_replay_websocket_preserves_buffered_binary_frame(self) -> None:
        binary_frame = {"type": "websocket.receive", "bytes": b"\\x00"}

        received = await ReplayWebSocket(FakeWebSocket([]), (binary_frame,)).receive()
        self.assertEqual(received, binary_frame)

        replay = ReplayWebSocket(FakeWebSocket([]), (binary_frame,))
        with self.assertRaisesRegex(RuntimeError, "Expected WebSocket text frame"):
            async for _ in replay.iter_text():
                pass

    async def test_replay_websocket_preserves_disconnect_and_stops_iteration(self) -> None:
        disconnect_frame = {"type": "websocket.disconnect", "code": 1000}

        received = await ReplayWebSocket(FakeWebSocket([]), (disconnect_frame,)).receive()
        self.assertEqual(received, disconnect_frame)

        replay = ReplayWebSocket(FakeWebSocket([]), (disconnect_frame,))
        self.assertEqual([message async for message in replay.iter_text()], [])

    async def test_no_binding_is_rejected_before_pipeline_construction(self) -> None:
        decision = await authorize_websocket(
            FakeRedis(),
            start_message("call-1"),
            counter=AdmissionCounter(),
            mode="enforce",
            binding_wait_seconds=0,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no_binding")
        self.assertFalse(decision.counter_reserved)

    async def test_enforce_rejection_never_calls_the_pipeline(self) -> None:
        server = import_server_without_dotenv()

        websocket = FakeEndpointWebSocket(
            [json.dumps({"event": "connected"}), start_message("call-1")],
            FakeRedis(),
        )
        with (
            patch.dict(os.environ, {"WS_AUTH_MODE": "enforce"}, clear=False),
            patch.object(server, "ws_admission_counter", server.AdmissionCounter()),
            patch.object(server, "run_bot", new=AsyncMock()) as run_bot,
        ):
            await server.websocket_endpoint(websocket)

        run_bot.assert_not_awaited()
        self.assertIn(1008, websocket.close_codes)

    async def test_failed_handshake_replays_consumed_frames_in_log_mode(self) -> None:
        server = import_server_without_dotenv()
        connected = json.dumps({"event": "connected"})
        websocket = FakeEndpointWebSocket(
            [connected, RuntimeError("binary frame")], FakeRedis()
        )

        async def assert_replayed(replay_websocket) -> None:
            self.assertEqual(await replay_websocket.receive_text(), connected)

        with (
            patch.dict(os.environ, {"WS_AUTH_MODE": "log"}, clear=False),
            patch.object(server, "ws_admission_counter", server.AdmissionCounter()),
            patch.object(server, "run_bot", new=AsyncMock(side_effect=assert_replayed)) as run_bot,
        ):
            await server.websocket_endpoint(websocket)

        run_bot.assert_awaited_once()

    async def test_request_demo_call_issues_a_binding(self) -> None:
        server = import_server_without_dotenv()
        redis = FakeRedis()
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(redis=redis)))
        exotel_response = server.JSONResponse(
            status_code=200,
            content={"status": "success", "call_sid": "call-1"},
        )

        with (
            patch.object(server, "check_demo_rate_limits", new=AsyncMock(return_value=None)),
            patch.object(server, "trigger_exotel_call", new=AsyncMock(return_value=exotel_response)),
        ):
            response = await server.request_demo_call(
                request, server.DemoCallRequest(phone_number="+919876543210")
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("ws_bind:call-1", redis.values)
        payload = json.loads(redis.values["ws_bind:call-1"])
        self.assertEqual(set(payload), {"issued_at"})
        self.assertIsInstance(payload["issued_at"], int)

    async def test_valid_binding_is_accepted_once(self) -> None:
        redis = FakeRedis()
        await issue_binding(redis, "call-1", issued_at=123)
        self.assertEqual(json.loads(redis.values["ws_bind:call-1"]), {"issued_at": 123})

        decision = await authorize_websocket(
            redis,
            start_message("call-1"),
            counter=AdmissionCounter(),
            mode="enforce",
            binding_wait_seconds=0,
        )

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.bound)
        self.assertEqual(redis.last_ttl, WS_AUTH_TTL_SECONDS)

    async def test_replay_of_a_consumed_binding_is_rejected(self) -> None:
        redis = FakeRedis()
        counter = AdmissionCounter()
        await issue_binding(redis, "call-1", issued_at=123)

        first = await authorize_websocket(
            redis,
            start_message("call-1"),
            counter=counter,
            mode="enforce",
            binding_wait_seconds=0,
        )
        counter.release()
        replay = await authorize_websocket(
            redis,
            start_message("call-1"),
            counter=counter,
            mode="enforce",
            binding_wait_seconds=0,
        )

        self.assertTrue(first.allowed)
        self.assertFalse(replay.allowed)
        self.assertEqual(replay.reason, "no_binding")

    async def test_over_limit_is_rejected(self) -> None:
        redis = FakeRedis()
        counter = AdmissionCounter()
        counter.acquire()
        await issue_binding(redis, "call-1", issued_at=123)

        decision = await authorize_websocket(
            redis,
            start_message("call-1"),
            counter=counter,
            mode="enforce",
            max_concurrent=1,
            binding_wait_seconds=0,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "concurrent_limit")
        self.assertEqual(counter.active, 1)

    async def test_log_mode_never_rejects(self) -> None:
        decision = await authorize_websocket(
            FakeRedis(),
            start_message("call-1"),
            counter=AdmissionCounter(),
            mode="log",
            binding_wait_seconds=0,
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "no_binding")
        self.assertTrue(decision.counter_reserved)

    async def test_redis_down_rejects_in_enforce_mode(self) -> None:
        decision = await authorize_websocket(
            UnavailableRedis(),
            start_message("call-1"),
            counter=AdmissionCounter(),
            mode="enforce",
            binding_wait_seconds=0,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "redis_unavailable")

    async def test_oversized_start_message_is_rejected(self) -> None:
        websocket = FakeWebSocket(["x" * 17])

        with self.assertRaises(StartMessageError) as raised:
            await read_start_handshake(websocket, timeout_seconds=1, max_bytes=16)

        self.assertEqual(raised.exception.reason, "start_message_too_large")

    async def test_late_start_message_is_rejected(self) -> None:
        websocket = FakeWebSocket([start_message("call-1")], delay=0.02)

        with self.assertRaises(StartMessageError) as raised:
            await read_start_handshake(websocket, timeout_seconds=0.001, max_bytes=1024)

        self.assertEqual(raised.exception.reason, "start_message_timeout")

    async def test_counter_is_released_when_pipeline_raises(self) -> None:
        redis = FakeRedis()
        counter = AdmissionCounter()
        await issue_binding(redis, "call-1", issued_at=123)

        with self.assertRaisesRegex(RuntimeError, "pipeline failed"):
            async with admission_session(
                redis,
                start_message("call-1"),
                counter=counter,
                mode="enforce",
                binding_wait_seconds=0,
            ) as decision:
                self.assertTrue(decision.allowed)
                raise RuntimeError("pipeline failed")

        self.assertEqual(counter.active, 0)


if __name__ == "__main__":
    unittest.main()
