"""Deepgram key terms, fallbacks, and privacy-preserving transcript checks."""

from asyncio import sleep
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

from loguru import logger
from deepgram import AsyncDeepgramClient
from deepgram.core.api_error import ApiError
from deepgram.core.events import EventType
from deepgram.listen.v1.types import ListenV1Results
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService, DeepgramSTTSettings
from pipecat.transcriptions.language import Language
from websockets.exceptions import InvalidStatus
from websockets.legacy.exceptions import InvalidStatusCode


FIXED_TERMS = ("crore", "crores", "lakh", "lakhs", "rupees", "BHK")
MAX_TERMS = 40
MAX_ESTIMATED_TOKENS = 400
_WORD = re.compile(r"[A-Za-z0-9]+(?:[.'-][A-Za-z0-9]+)*")
_NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?|[A-Za-z]+")
_NUMBER_WORDS = {
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
    "hundred",
    "thousand",
    "million",
    "point",
    "decimal",
    "half",
    "quarter",
    "and",
}
_AMOUNT_UNITS = {"lakh", "lakhs", "crore", "crores", "cr", "rupees", "thousand"}


def build_keyterms(project_kb: dict) -> list[str]:
    """Return bounded Deepgram key terms from the four approved KB fields."""
    location = project_kb.get("location")
    if not isinstance(location, dict):
        location = {}
    candidates: list[Any] = [
        project_kb.get("project_name"),
        project_kb.get("developer"),
        location.get("city"),
        location.get("sector"),
        *FIXED_TERMS,
    ]
    terms: list[str] = []
    seen: set[str] = set()
    estimated_tokens = 0
    truncated = False
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        term = candidate.strip()
        folded = term.casefold()
        if not term or ":" in term or folded in seen:
            continue
        term_tokens = len(term.split()) * 2
        if len(terms) >= MAX_TERMS or estimated_tokens + term_tokens > MAX_ESTIMATED_TOKENS:
            truncated = True
            continue
        terms.append(term)
        seen.add(folded)
        estimated_tokens += term_tokens
    if truncated:
        logger.warning("Deepgram key terms were truncated to the configured limits")
    return terms


def build_stt_settings(
    project_kb: dict,
    *,
    language_mode: str,
    keyterms: bool,
    numerals: bool,
) -> DeepgramSTTSettings:
    """Build the exact Deepgram settings shared by calls and the probe."""
    values: dict[str, Any] = {
        "model": "nova-3",
        "language": "multi" if language_mode == "hinglish" else "en-IN",
        "smart_format": True,
        "interim_results": True,
        "endpointing": 300,
    }
    if keyterms:
        values["keyterm"] = build_keyterms(project_kb)
    if numerals:
        values["numerals"] = True
    return DeepgramSTTSettings(**values)


def _websocket_rejection_status(error: Exception) -> int | None:
    """Return a fallback-eligible HTTP WebSocket-upgrade status."""
    if isinstance(error, ApiError):
        status = error.status_code
    elif isinstance(error, InvalidStatusCode):
        status = error.status_code
    elif isinstance(error, InvalidStatus):
        status = error.response.status_code
    else:
        return None
    return status if 400 <= status < 500 and status not in {401, 403, 429} else None


def _project_check(text: str, project_name: str | None) -> str:
    project_words = _WORD.findall(project_name or "")
    transcript_words = _WORD.findall(text)
    if not project_words or not transcript_words:
        return "none"
    expected = " ".join(project_words).casefold()
    width = len(project_words)
    windows = [transcript_words[index : index + width] for index in range(len(transcript_words) - width + 1)]
    for window in windows:
        if " ".join(window).casefold() == expected:
            return "exact"

    best_fragment = ""
    best_ratio = 0.0
    for window in windows:
        fragment = " ".join(window)
        ratio = SequenceMatcher(None, fragment.casefold(), expected).ratio()
        if ratio > best_ratio:
            best_fragment = fragment
            best_ratio = ratio
    if best_ratio < 0.6:
        return "none"
    safe_fragment = all(
        SequenceMatcher(None, heard.casefold(), wanted.casefold()).ratio() >= 0.6
        for heard, wanted in zip(best_fragment.split(), project_words)
    )
    return f'near:"{best_fragment}"' if safe_fragment else "near"


def _is_number_token(token: str) -> bool:
    return bool(re.fullmatch(r"\d+(?:\.\d+)?", token)) or token.casefold() in _NUMBER_WORDS


def _amount_check(text: str) -> str:
    tokens = _NUMBER_TOKEN.findall(text)
    for index, token in enumerate(tokens):
        if token.casefold() not in _AMOUNT_UNITS:
            continue
        start = index
        while start > 0 and _is_number_token(tokens[start - 1]):
            start -= 1
        if start < index:
            number_tokens = tokens[start:index]
            digit_count = sum(
                len(re.sub(r"\D", "", number_token))
                for number_token in number_tokens
            )
            if len(number_tokens) >= 2 or digit_count >= 5:
                return f'"[number] {token}"'
            return f'"{" ".join(tokens[start : index + 1])}"'

    bare = re.fullmatch(r"\s*(\d{1,4}(?:\.\d+)?)\s*", text)
    return f'"{bare.group(1)} [no unit]"' if bare else "none"


def _script(text: str) -> str:
    deva = sum(
        unicodedata.category(char).startswith("L") and "\u0900" <= char <= "\u097f"
        for char in text
    )
    latin = sum(
        unicodedata.category(char).startswith("L")
        and (("A" <= char <= "Z") or ("a" <= char <= "z"))
        for char in text
    )
    total = deva + latin
    if total == 0:
        return "none"
    share = deva / total
    if share >= 0.8:
        return "deva"
    if share <= 0.2:
        return "latin"
    return "mixed"


def summarize_transcript(
    text: str,
    project_name: str | None,
    *,
    hinglish: bool = False,
    language_code: str | None = None,
) -> str:
    """Summarize only the two STT checks approved for production logging."""
    words = len(text.split()) if hinglish else len(_WORD.findall(text))
    project = _project_check(text, project_name)
    amount = _amount_check(text)
    summary = f"words={words} project={project} amount={amount}"
    if hinglish:
        language = language_code or "none"
        if language != "none" and not re.fullmatch(
            r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", language
        ):
            language = "other"
        summary += f" script={_script(text)} lang={language}"
    return summary


class STTCheckingDeepgramService(DeepgramSTTService):
    """Deepgram service that reports endpoint selection and scrubbed STT checks."""

    def __init__(
        self,
        *,
        conn_id: str | None = None,
        region: str = "global",
        project_name: str | None = None,
        hinglish: bool = False,
        **kwargs: Any,
    ) -> None:
        self._nxlyr_api_key = kwargs.get("api_key")
        self._nxlyr_conn = conn_id if conn_id and re.fullmatch(r"[0-9a-f]{6}", conn_id) else "-"
        self._nxlyr_region = region
        self._nxlyr_project_name = str(project_name or "")
        self._nxlyr_hinglish = hinglish
        self._nxlyr_language_code: str | None = None
        self._nxlyr_final = 0
        super().__init__(**kwargs)
        self._nxlyr_initial_client = self._client
        self._nxlyr_initial_region = region
        self._nxlyr_initial_keyterms = self._build_connect_kwargs().get("keyterm")
        self._nxlyr_fallback_steps: set[str] = set()
        host = self._endpoint_host()
        language = self._build_connect_kwargs().get("language", "unknown")
        logger.info(
            f"stt endpoint: conn={self._nxlyr_conn} region={region} host={host} "
            f"language={language}"
        )
        if region == "eu" and host != "api.eu.deepgram.com":
            logger.warning(
                f"stt endpoint mismatch: conn={self._nxlyr_conn} region=eu host={host}"
            )

    async def _connection_handler(self) -> None:
        if not self._nxlyr_hinglish:
            await super()._connection_handler()
            return

        backoff = 0.5
        while True:
            connect_kwargs = self._build_connect_kwargs()
            keepalive_task = None
            retry_delay = None
            try:
                async with self._client.listen.v1.connect(
                    **connect_kwargs
                ) as connection:
                    backoff = 0.5
                    self._connection = connection
                    self._connection_ready.set()
                    connection.on(EventType.MESSAGE, self._on_message)
                    connection.on(EventType.ERROR, self._on_error)
                    logger.debug(f"{self}: Websocket connection initialized")
                    keepalive_task = self.create_task(
                        self._keepalive_handler(), f"{self}::keepalive"
                    )
                    await connection.start_listening()
            except Exception as error:
                logger.warning(
                    f"{self}: Connection lost, will retry: {type(error).__name__}"
                )
                status = _websocket_rejection_status(error)
                if status is not None and self._apply_next_hinglish_fallback(status):
                    backoff = 0.5
                else:
                    retry_delay = backoff
                    backoff = min(backoff * 2, 2.0)
            finally:
                self._connection_ready.clear()
                self._connection = None
                if keepalive_task:
                    await self.cancel_task(keepalive_task)
            if retry_delay is not None:
                await sleep(retry_delay)

    def _apply_next_hinglish_fallback(self, status: int) -> bool:
        if "global_host" not in self._nxlyr_fallback_steps:
            self._nxlyr_fallback_steps.add("global_host")
            if self._nxlyr_region == "eu":
                self._client = AsyncDeepgramClient(api_key=self._nxlyr_api_key)
                self._nxlyr_region = "global"
                self._log_fallback("global_host", status)
                return True

        if "without_keyterms" not in self._nxlyr_fallback_steps:
            self._nxlyr_fallback_steps.add("without_keyterms")
            if "keyterm" in self._build_connect_kwargs():
                self._settings.keyterm = None
                self._log_fallback("without_keyterms", status)
                return True

        if "english" not in self._nxlyr_fallback_steps:
            self._nxlyr_fallback_steps.add("english")
            self._settings.language = "en-IN"
            self._settings.keyterm = self._nxlyr_initial_keyterms
            self._client = self._nxlyr_initial_client
            self._nxlyr_region = self._nxlyr_initial_region
            self._log_fallback("english", status)
            return True
        return False

    def _log_fallback(self, step: str, status: int) -> None:
        logger.info(f"stt fallback: step={step} http_status={status}")

    def _endpoint_host(self) -> str:
        try:
            production = self._client._client_wrapper._environment.production
            return urlsplit(production).hostname or "unknown"
        except Exception:
            return "unknown"

    async def _on_message(self, message) -> None:
        self._nxlyr_language_code = None
        if isinstance(message, ListenV1Results) and message.channel:
            alternatives = message.channel.alternatives
            if alternatives and alternatives[0].languages:
                code = alternatives[0].languages[0]
                self._nxlyr_language_code = str(code)
                try:
                    Language(code)
                except (TypeError, ValueError):
                    safe_alternative = alternatives[0].model_copy(
                        update={"languages": None}
                    )
                    safe_channel = message.channel.model_copy(
                        update={"alternatives": [safe_alternative, *alternatives[1:]]}
                    )
                    message = message.model_copy(update={"channel": safe_channel})
        await super()._on_message(message)

    async def push_frame(
        self,
        frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        if isinstance(frame, TranscriptionFrame):
            self._nxlyr_final += 1
            try:
                summary = summarize_transcript(
                    frame.text,
                    self._nxlyr_project_name,
                    hinglish=self._nxlyr_hinglish,
                    language_code=self._nxlyr_language_code,
                )
                logger.info(
                    f"stt check: conn={self._nxlyr_conn} final={self._nxlyr_final} {summary}"
                )
            except Exception as error:
                logger.warning(
                    f"stt check failed: conn={self._nxlyr_conn} "
                    f"error={type(error).__name__}"
                )
        await super().push_frame(frame, direction)
