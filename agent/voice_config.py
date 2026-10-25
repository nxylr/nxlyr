"""Per-call ElevenLabs settings and the server's small keep-warm request."""

import asyncio
import math
import os
import re
from dataclasses import dataclass, field
from time import monotonic
from typing import Mapping

import aiohttp
from loguru import logger
from pipecat.services.elevenlabs.tts import (
    ElevenLabsHttpTTSSettings,
    build_elevenlabs_voice_settings,
)
from pipecat.utils.text.base_text_filter import BaseTextFilter

from tools import make_redis_client


MODELS = frozenset({
    "eleven_flash_v2_5", "eleven_v4_turbo", "eleven_turbo_v2_5",
    "eleven_turbo_v2", "eleven_multilingual_v2",
})
SETTING_FIELDS = (
    "stability", "similarity_boost", "style", "use_speaker_boost", "speed",
    "optimize_streaming_latency",
)
V4_DROPPABLE = ("style", "speed", "use_speaker_boost", "optimize_streaming_latency")
ENV_NAMES = {
    "provider": "TTS_PROVIDER",
    "model": "ELEVENLABS_MODEL",
    "voice": "ELEVENLABS_VOICE_ID",
    "stability": "ELEVENLABS_STABILITY",
    "similarity_boost": "ELEVENLABS_SIMILARITY_BOOST",
    "style": "ELEVENLABS_STYLE",
    "use_speaker_boost": "ELEVENLABS_USE_SPEAKER_BOOST",
    "speed": "ELEVENLABS_SPEED",
    "optimize_streaming_latency": "ELEVENLABS_OPTIMIZE_STREAMING_LATENCY",
}
DEFAULTS = {
    "provider": "elevenlabs", "model": "eleven_turbo_v2",
    "voice": "21m00Tcm4TlvDq8ikWAM", "stability": None,
    "similarity_boost": None, "style": None, "use_speaker_boost": None,
    "speed": None, "optimize_streaming_latency": None, "keepwarm_seconds": 240,
}


@dataclass(frozen=True)
class VoiceConfig:
    provider: str = "elevenlabs"
    model: str = "eleven_turbo_v2"
    voice: str = "21m00Tcm4TlvDq8ikWAM"
    stability: float | None = None
    similarity_boost: float | None = None
    style: float | None = None
    use_speaker_boost: bool | None = None
    speed: float | None = None
    optimize_streaming_latency: int | None = None
    keepwarm_seconds: int = 240
    overrides: tuple[str, ...] = field(default_factory=tuple)


def _parse(name: str, raw: str):
    if name == "provider":
        if raw == "elevenlabs":
            return raw
    elif name == "model":
        if raw in MODELS:
            return raw
    elif name == "voice":
        if re.fullmatch(r"[A-Za-z0-9]{15,40}", raw):
            return raw
    elif name == "use_speaker_boost":
        if raw.lower() in ("true", "1", "false", "0"):
            return raw.lower() in ("true", "1")
    elif name in ("optimize_streaming_latency", "keepwarm_seconds"):
        if re.fullmatch(r"[0-9]+", raw):
            value = int(raw)
            if name == "optimize_streaming_latency" and 0 <= value <= 4:
                return value
            if name == "keepwarm_seconds" and (value == 0 or 60 <= value <= 3600):
                return value
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            pass
        else:
            low, high = (0.7, 1.2) if name == "speed" else (0.0, 1.0)
            if math.isfinite(value) and low <= value <= high:
                return value
    raise ValueError(name)


def resolve(override: Mapping[str, str] | None, environment: Mapping[str, str]) -> VoiceConfig:
    """Resolve each field independently: valid Redis, valid env, then code default."""
    override = override or {}
    for unknown in override.keys() - DEFAULTS.keys():
        logger.warning("Unknown voice:config field {}; ignoring", unknown)
    values = {}
    used = []
    for name, default in DEFAULTS.items():
        sources = [("redis", override[name])] if name in override else []
        env_name = ENV_NAMES.get(name)
        if env_name and env_name in environment and environment[env_name] != "":
            sources.append(("env", environment[env_name]))
        values[name] = default
        for source, raw in sources:
            try:
                values[name] = _parse(name, raw)
                if source == "redis":
                    used.append(name)
                break
            except (ValueError, TypeError, AttributeError):
                logger.warning("Invalid voice:config value for {}; using fallback", name)
    return VoiceConfig(**values, overrides=tuple(used))


async def read_override(redis_client=None, *, quiet: bool = False) -> dict[str, str] | None:
    """Read the short-lived Redis override without holding up or failing a call."""
    client = redis_client
    if client is None and not os.getenv("REDIS_URL"):
        logger.warning("voice:config unavailable error_type=MissingRedisURL")
        return None

    async def read():
        nonlocal client
        if client is None:
            if quiet:
                # Keep-warm ticks do not need make_redis_client's INFO line.
                import redis.asyncio as redis_asyncio

                client = redis_asyncio.from_url(
                    os.environ["REDIS_URL"], decode_responses=True,
                    socket_connect_timeout=1.0, socket_timeout=2.0,
                )
            else:
                client = await make_redis_client()
        if client is None:
            raise ConnectionError("Redis unavailable")
        return await client.hgetall("voice:config")

    try:
        return await asyncio.wait_for(read(), timeout=1.0)
    except Exception as error:
        logger.warning("voice:config unavailable error_type={}", type(error).__name__)
        return None
    finally:
        if client is not None:
            try:
                await asyncio.wait_for(client.aclose(), timeout=1.0)
            except Exception as error:
                logger.warning("voice:config close failed error_type={}", type(error).__name__)


def is_v4(model: str) -> bool:
    return model.startswith("eleven_v4")


def sent_fields(cfg: VoiceConfig) -> dict[str, float | bool | int]:
    return {
        name: value for name in SETTING_FIELDS
        if (value := getattr(cfg, name)) is not None
        and not (is_v4(cfg.model) and name in V4_DROPPABLE)
    }


def dropped_fields(cfg: VoiceConfig) -> tuple[str, ...]:
    if not is_v4(cfg.model):
        return ()
    return tuple(name for name in V4_DROPPABLE if getattr(cfg, name) is not None)


def to_settings(cfg: VoiceConfig) -> ElevenLabsHttpTTSSettings:
    return ElevenLabsHttpTTSSettings(model=cfg.model, voice=cfg.voice, **sent_fields(cfg))


def log_line(cfg: VoiceConfig, conn_id: str | None) -> str:
    sent = sent_fields(cfg)
    parts = [
        f"voice config: conn={conn_id or 'none'} provider={cfg.provider}",
        f"model={cfg.model} voice={cfg.voice}",
    ]
    parts += [f"{name}={sent[name] if name in sent else 'unset'}" for name in SETTING_FIELDS]
    parts += [
        f"overrides={','.join(cfg.overrides) or 'none'}",
        f"dropped={','.join(dropped_fields(cfg)) or 'none'}",
    ]
    return " ".join(parts)


class StripTagsFilter(BaseTextFilter):
    async def filter(self, text: str) -> str:
        without_tags = re.sub(r"\[[^\[\]]{1,40}\]", "", text)
        if without_tags == text:
            return text
        return re.sub(r" {2,}", " ", without_tags).strip()


def tts_filters(cfg: VoiceConfig) -> list[BaseTextFilter]:
    return [] if is_v4(cfg.model) else [StripTagsFilter()]


async def keep_warm_once(
    session: aiohttp.ClientSession, cfg: VoiceConfig, api_key: str
) -> tuple[bool, int]:
    """Warm the configured voice with a three-character HTTP TTS request."""
    settings = to_settings(cfg)
    payload = {"text": "Hi.", "model_id": cfg.model}
    voice_settings = build_elevenlabs_voice_settings(sent_fields(cfg))
    if voice_settings:
        payload["voice_settings"] = voice_settings
    params = {"output_format": "pcm_8000"}
    if cfg.optimize_streaming_latency is not None and not is_v4(cfg.model):
        params["optimize_streaming_latency"] = str(cfg.optimize_streaming_latency)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{settings.voice}/stream/with-timestamps"
    started = monotonic()
    try:
        async with asyncio.timeout(10):
            async with session.post(
                url, json=payload, params=params,
                headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "voice keep-warm failed status={} error_type=none", response.status
                    )
                    return False, response.status
                await response.content.read(1)
                ttfb_ms = max(0, int((monotonic() - started) * 1000))
                await response.read()
                return True, ttfb_ms
    except Exception as error:
        logger.warning(
            "voice keep-warm failed status=none error_type={}", type(error).__name__
        )
        return False, 0
