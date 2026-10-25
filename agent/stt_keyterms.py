"""Deepgram key terms and privacy-preserving transcript checks."""

import re
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlsplit

from loguru import logger
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.deepgram.stt import DeepgramSTTService


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


def summarize_transcript(text: str, project_name: str | None) -> str:
    """Summarize only the two STT checks approved for production logging."""
    words = len(_WORD.findall(text))
    project = _project_check(text, project_name)
    amount = _amount_check(text)
    return f"words={words} project={project} amount={amount}"


class STTCheckingDeepgramService(DeepgramSTTService):
    """Deepgram service that reports endpoint selection and scrubbed STT checks."""

    def __init__(
        self,
        *,
        conn_id: str | None = None,
        region: str = "global",
        project_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        self._nxlyr_conn = conn_id if conn_id and re.fullmatch(r"[0-9a-f]{6}", conn_id) else "-"
        self._nxlyr_region = region
        self._nxlyr_project_name = str(project_name or "")
        self._nxlyr_final = 0
        super().__init__(**kwargs)
        host = self._endpoint_host()
        logger.info(
            f"stt endpoint: conn={self._nxlyr_conn} region={region} host={host}"
        )
        if region == "eu" and host != "api.eu.deepgram.com":
            logger.warning(
                f"stt endpoint mismatch: conn={self._nxlyr_conn} region=eu host={host}"
            )

    def _endpoint_host(self) -> str:
        try:
            production = self._client._client_wrapper._environment.production
            return urlsplit(production).hostname or "unknown"
        except Exception:
            return "unknown"

    async def push_frame(
        self,
        frame,
        direction: FrameDirection = FrameDirection.DOWNSTREAM,
    ) -> None:
        if isinstance(frame, TranscriptionFrame):
            self._nxlyr_final += 1
            try:
                summary = summarize_transcript(frame.text, self._nxlyr_project_name)
                logger.info(
                    f"stt check: conn={self._nxlyr_conn} final={self._nxlyr_final} {summary}"
                )
            except Exception as error:
                logger.warning(
                    f"stt check failed: conn={self._nxlyr_conn} "
                    f"error={type(error).__name__}"
                )
        await super().push_frame(frame, direction)
