"""One-shot Redis bindings and admission control for Exotel WebSockets."""

import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator


WS_AUTH_TTL_SECONDS = 120
DEFAULT_START_TIMEOUT_SECONDS = 5.0
DEFAULT_START_MAX_BYTES = 16 * 1024
DEFAULT_BINDING_WAIT_SECONDS = 3.0
DEFAULT_BINDING_POLL_SECONDS = 0.1
DEFAULT_REDIS_TIMEOUT_SECONDS = 1.0


def binding_key(call_sid: str) -> str:
    return f"ws_bind:{call_sid}"


async def issue_binding(redis_client: Any, call_sid: str, *, issued_at: int | None = None) -> None:
    """Create the short-lived, one-shot binding for a demo call's Exotel SID."""
    if not isinstance(call_sid, str) or not call_sid or len(call_sid) > 256:
        raise ValueError("Exotel call SID is missing or invalid")

    payload = json.dumps({"issued_at": int(time.time()) if issued_at is None else issued_at})
    await redis_client.set(binding_key(call_sid), payload, ex=WS_AUTH_TTL_SECONDS)


@dataclass(frozen=True)
class StartHandshake:
    call_sid: str
    start_message: str
    messages: tuple[dict[str, Any], ...]


class StartMessageError(ValueError):
    """A start handshake is absent, malformed, too large, or arrived too late."""

    def __init__(self, reason: str, messages: tuple[dict[str, Any], ...] = ()) -> None:
        self.reason = reason
        self.messages = messages
        super().__init__(reason)


def _parse_start_message(message: str, *, max_bytes: int) -> tuple[str, str | None]:
    if len(message.encode("utf-8")) > max_bytes:
        raise StartMessageError("start_message_too_large")

    try:
        payload = json.loads(message)
    except json.JSONDecodeError as error:
        raise StartMessageError("invalid_start_message") from error

    if not isinstance(payload, dict):
        raise StartMessageError("invalid_start_message")

    event = payload.get("event")
    if event == "connected":
        return event, None
    if event != "start":
        raise StartMessageError("invalid_start_message")

    start = payload.get("start")
    call_sid = start.get("call_sid") if isinstance(start, dict) else None
    if not isinstance(call_sid, str) or not call_sid or len(call_sid) > 256:
        raise StartMessageError("invalid_start_message")
    return event, call_sid


async def read_start_handshake(
    websocket: Any,
    *,
    timeout_seconds: float = DEFAULT_START_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_START_MAX_BYTES,
) -> StartHandshake:
    """Read Exotel's optional ``connected`` frame and required ``start`` frame."""
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    messages: list[dict[str, Any]] = []

    for _ in range(2):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise StartMessageError("start_message_timeout", tuple(messages))
        try:
            frame = await asyncio.wait_for(websocket.receive(), remaining)
        except TimeoutError as error:
            raise StartMessageError("start_message_timeout", tuple(messages)) from error
        except Exception as error:
            raise StartMessageError("start_message_unavailable", tuple(messages)) from error

        if not isinstance(frame, dict):
            raise StartMessageError("invalid_start_message", tuple(messages))
        messages.append(frame)
        message = frame.get("text")
        if not isinstance(message, str):
            raise StartMessageError("invalid_start_message", tuple(messages))
        try:
            event, call_sid = _parse_start_message(message, max_bytes=max_bytes)
        except Exception as error:
            reason = getattr(error, "reason", "invalid_start_message")
            raise StartMessageError(reason, tuple(messages)) from error
        if event == "start":
            return StartHandshake(
                call_sid=call_sid,
                start_message=message,
                messages=tuple(messages),
            )

    raise StartMessageError("invalid_start_message", tuple(messages))


class ReplayWebSocket:
    """Replay admission-consumed handshake frames before delegating to a socket."""

    def __init__(self, websocket: Any, messages: tuple[dict[str, Any], ...]) -> None:
        self._websocket = websocket
        self._messages = deque(messages)

    async def receive_text(self) -> str:
        if self._messages:
            message = self._messages.popleft().get("text")
            if not isinstance(message, str):
                raise RuntimeError("Expected WebSocket text frame")
            return message
        return await self._websocket.receive_text()

    async def receive(self) -> dict[str, str]:
        if self._messages:
            return self._messages.popleft()
        return await self._websocket.receive()

    async def receive_json(self, mode: str = "text") -> Any:
        if self._messages:
            return json.loads(await self.receive_text())
        return await self._websocket.receive_json(mode=mode)

    async def iter_text(self) -> AsyncIterator[str]:
        while self._messages:
            if self._messages[0].get("type") == "websocket.disconnect":
                self._messages.popleft()
                return
            yield await self.receive_text()
        async for message in self._websocket.iter_text():
            yield message

    def __getattr__(self, name: str) -> Any:
        return getattr(self._websocket, name)


def format_call_sid(call_sid: str | None) -> str:
    """Render an untrusted SID safely for logs without letting it dominate them."""
    return repr(call_sid)[:64]


@dataclass
class AdmissionCounter:
    """Per-process count of WebSocket sessions handed to the pipeline."""

    active: int = 0

    def acquire(self) -> None:
        self.active += 1

    def try_acquire(self, maximum: int) -> bool:
        if self.active >= maximum:
            return False
        self.acquire()
        return True

    def release(self) -> None:
        if self.active <= 0:
            raise RuntimeError("WebSocket admission counter underflow")
        self.active -= 1


@dataclass(frozen=True)
class AdmissionDecision:
    allowed: bool
    reason: str | None
    call_sid: str | None
    bound: bool
    counter_reserved: bool


async def _consume_binding(
    redis_client: Any,
    call_sid: str,
    *,
    wait_seconds: float,
    poll_seconds: float,
    redis_timeout_seconds: float = DEFAULT_REDIS_TIMEOUT_SECONDS,
) -> tuple[bool, str | None]:
    if redis_client is None:
        return False, "redis_unavailable"

    deadline = asyncio.get_running_loop().time() + wait_seconds
    while True:
        try:
            binding = await asyncio.wait_for(
                redis_client.getdel(binding_key(call_sid)), redis_timeout_seconds
            )
        except TimeoutError:
            return False, "redis_timeout"
        except Exception:
            return False, "redis_unavailable"

        if binding is not None:
            try:
                payload = json.loads(binding)
            except (TypeError, json.JSONDecodeError):
                return False, "invalid_binding"
            if isinstance(payload, dict) and isinstance(payload.get("issued_at"), int):
                return True, None
            return False, "invalid_binding"

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return False, "no_binding"
        await asyncio.sleep(min(poll_seconds, remaining))


async def authorize_websocket(
    redis_client: Any,
    start_message: str | None,
    *,
    counter: AdmissionCounter,
    mode: str,
    max_concurrent: int = 10,
    binding_wait_seconds: float = DEFAULT_BINDING_WAIT_SECONDS,
    binding_poll_seconds: float = DEFAULT_BINDING_POLL_SECONDS,
    redis_timeout_seconds: float = DEFAULT_REDIS_TIMEOUT_SECONDS,
) -> AdmissionDecision:
    """Consume a binding and reserve a pipeline slot without constructing it."""
    normalized_mode = "enforce" if mode.lower() == "enforce" else "log"
    maximum = max(1, max_concurrent)

    try:
        _, call_sid = _parse_start_message(
            start_message if isinstance(start_message, str) else "",
            max_bytes=DEFAULT_START_MAX_BYTES,
        )
        if call_sid is None:
            raise StartMessageError("invalid_start_message")
    except StartMessageError as error:
        reason = error.reason
        call_sid = None
        bound = False
    else:
        bound, reason = await _consume_binding(
            redis_client,
            call_sid,
            wait_seconds=binding_wait_seconds,
            poll_seconds=binding_poll_seconds,
            redis_timeout_seconds=redis_timeout_seconds,
        )

    if reason is None and counter.try_acquire(maximum):
        return AdmissionDecision(True, None, call_sid, bound, True)
    if reason is None:
        reason = "concurrent_limit"

    if normalized_mode == "log":
        counter.acquire()
        return AdmissionDecision(True, reason, call_sid, bound, True)
    return AdmissionDecision(False, reason, call_sid, bound, False)


@asynccontextmanager
async def admission_session(
    redis_client: Any,
    start_message: str | None,
    **kwargs: Any,
) -> AsyncIterator[AdmissionDecision]:
    """Release the in-process admission slot on every pipeline exit path."""
    decision = await authorize_websocket(redis_client, start_message, **kwargs)
    try:
        yield decision
    finally:
        if decision.counter_reserved:
            kwargs["counter"].release()
