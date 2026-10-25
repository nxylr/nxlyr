"""Per-call conversation switches read from the Redis ``convo:config`` hash."""

import asyncio
import os
import re
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from typing import Any, Mapping

import redis.asyncio as redis
from loguru import logger


REDIS_TIMEOUT_SECONDS = 0.5
CONFIG_KEY = "convo:config"
_ALLOWED = {
    "prompt_version": {"v2", "v21"},
    "stt_keyterms": {"on", "off"},
    "stt_numerals": {"on", "off"},
    "stt_region": {"global", "eu"},
    "greeting_tags": {"on", "off"},
}
_DEFAULT_RAW = {
    "prompt_version": "v2",
    "stt_keyterms": "off",
    "stt_numerals": "off",
    "stt_region": "global",
    "greeting_tags": "off",
}


@dataclass(frozen=True)
class ConvoConfig:
    prompt_version: str = "v2"
    stt_keyterms: bool = False
    stt_numerals: bool = False
    stt_region: str = "global"
    greeting_tags: bool = False
    overrides: tuple[str, ...] = ()
    read_ms: int = 0
    overrides_available: bool = True


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def parse(
    raw_config: Mapping[Any, Any] | None,
    *,
    read_ms: int = 0,
) -> ConvoConfig:
    """Parse a Redis hash without allowing a malformed switch to affect a call."""
    overrides_available = True
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, Mapping):
        logger.warning(
            f"Invalid convo:config payload ({type(raw_config).__name__}); using defaults"
        )
        raw_config = {}
        overrides_available = False

    normalized = {_text(key): value for key, value in raw_config.items()}
    for field in normalized.keys() - _ALLOWED.keys():
        logger.warning(f"Unknown convo:config field {field[:40]!r}; ignoring")

    parsed = dict(_DEFAULT_RAW)
    overrides: list[str] = []
    for field, allowed in _ALLOWED.items():
        if field not in normalized:
            continue
        value = _text(normalized[field]).strip().lower()
        if value not in allowed:
            logger.warning(
                f"Invalid convo:config value for {field}; using default"
            )
            continue
        parsed[field] = value
        overrides.append(field)

    return ConvoConfig(
        prompt_version=parsed["prompt_version"],
        stt_keyterms=parsed["stt_keyterms"] == "on",
        stt_numerals=parsed["stt_numerals"] == "on",
        stt_region=parsed["stt_region"],
        greeting_tags=parsed["greeting_tags"] == "on",
        overrides=tuple(overrides),
        read_ms=max(0, int(read_ms)),
        overrides_available=overrides_available,
    )


async def read_convo_config() -> ConvoConfig:
    """Read ``convo:config`` once, returning defaults on every failure."""
    started_at = monotonic()
    client = None
    try:
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            raise RuntimeError("REDIS_URL is unset")
        client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=REDIS_TIMEOUT_SECONDS,
            socket_timeout=REDIS_TIMEOUT_SECONDS,
        )
        raw_config = await asyncio.wait_for(
            client.hgetall(CONFIG_KEY), timeout=REDIS_TIMEOUT_SECONDS
        )
        read_ms = int((monotonic() - started_at) * 1000)
        return parse(raw_config, read_ms=read_ms)
    except Exception as error:
        logger.warning(
            f"convo:config read failed ({type(error).__name__}); using defaults"
        )
        return ConvoConfig(
            read_ms=int((monotonic() - started_at) * 1000),
            overrides_available=False,
        )
    finally:
        if client is not None:
            with suppress(Exception):
                await asyncio.wait_for(client.aclose(), timeout=0.05)


def tags_allowed(model: str | None) -> bool:
    return bool(model and model.startswith("eleven_v4"))


def log_line(
    config: ConvoConfig,
    conn_id: str | None,
    *,
    greeting_tags_blocked: bool = False,
) -> str:
    conn = conn_id if conn_id and re.fullmatch(r"[0-9a-f]{6}", conn_id) else "-"
    if greeting_tags_blocked:
        greeting_tags = "blocked"
    else:
        greeting_tags = "on" if config.greeting_tags else "off"
    overrides = (
        ",".join(config.overrides) or "none"
        if config.overrides_available
        else "unavailable"
    )
    return (
        f"convo config: conn={conn} prompt_version={config.prompt_version} "
        f"stt_keyterms={'on' if config.stt_keyterms else 'off'} "
        f"stt_numerals={'on' if config.stt_numerals else 'off'} "
        f"stt_region={config.stt_region} greeting_tags={greeting_tags} "
        f"read_ms={config.read_ms} overrides={overrides}"
    )
