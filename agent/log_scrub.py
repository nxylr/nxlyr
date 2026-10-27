"""Safe loguru configuration for container logs."""

import os
import re
import sys
from typing import TextIO

from loguru import logger


REDIS_URL = re.compile(r"(?:rediss?|unix)://\S*")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
SK_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
TELEGRAM_TOKEN = re.compile(r"\bbot\d{6,}:[A-Za-z0-9_-]{30,}\b")
BEARER_TOKEN = re.compile(r"Bearer\s+\S+")
INDIAN_MOBILE = re.compile(r"(?<![A-Za-z0-9])(?:\+91|91|0)?[6-9]\d{9}(?![A-Za-z0-9])")
INTERNATIONAL_PHONE = re.compile(r"(?<![A-Za-z0-9])\+\d{10,15}(?![A-Za-z0-9])")


def scrub(text: str) -> str:
    """Remove secrets and mask phone numbers in a fully formatted log message."""
    text = REDIS_URL.sub("[redis-url removed]", text)
    for name, value in os.environ.items():
        if (name.endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")) or name == "REDIS_URL") and len(value) >= 8:
            text = text.replace(value, "[secret removed]")
    text = JWT.sub("[secret removed]", text)
    text = SK_KEY.sub("[secret removed]", text)
    text = TELEGRAM_TOKEN.sub("[secret removed]", text)
    text = BEARER_TOKEN.sub("[secret removed]", text)

    def mask_phone(match: re.Match[str]) -> str:
        return f"****{match.group()[-4:]}"

    text = INDIAN_MOBILE.sub(mask_phone, text)
    return INTERNATIONAL_PHONE.sub(mask_phone, text)


def drop_prompt_debug(record: dict) -> bool:
    """Drop DEBUG records that carry prompts or raw function arguments."""
    if record["level"].no >= 20:
        return True
    if record["name"] == "pipecat.services.openai.base_llm":
        return False
    return not (
        record["name"] == "pipecat.services.llm_service"
        and "with arguments" in record["message"]
    )


def configure_logging(level: str | None, stream: TextIO | None = None) -> None:
    """Install the single process-wide safe loguru handler."""
    def sink(message) -> None:
        target = stream if stream is not None else sys.stderr
        try:
            target.write(scrub(str(message)))
        except Exception:
            try:
                target.write("[log scrubber failed]\n")
            except Exception:
                # Letting this escape makes Loguru print the raw record.
                pass

    logger.remove()
    logger.add(sink, level=level or "DEBUG", diagnose=False, filter=drop_prompt_debug)
