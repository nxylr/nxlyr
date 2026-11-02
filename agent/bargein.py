"""Smart barge-in classification, turn start strategy, tracing, and serialization."""

import asyncio
import base64
import json
import re
import unicodedata
from collections.abc import Awaitable, Callable
from enum import Enum
from time import monotonic

from loguru import logger

from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    AudioRawFrame,
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection
from pipecat.serializers.exotel import ExotelFrameSerializer
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start import BaseUserTurnStartStrategy


STOP_PHRASES = (
    "wait",
    "stop",
    "hold on",
    "ruko",
    "ek minute",
    "nahi",
    "no",
    "actually",
    "sorry",
    "excuse me",
    "sunno",
    "रुको",
    "एक मिनट",
    "नहीं",
    "सुनो",
    "रुकिए",
)

AGREEMENT_PHRASES = (
    "haan",
    "haanji",
    "ha",
    "accha",
    "theek hai",
    "thik hai",
    "theek",
    "thik",
    "hmm",
    "mm-hmm",
    "mmhmm",
    "han",
    "ok",
    "okay",
    "yes",
    "ji",
    "right",
    "sure",
    "yeah",
    "yep",
    "uh-huh",
    "mhm",
    "haan ji",
    "हाँ",
    "हां",
    "हाँ जी",
    "जी",
    "अच्छा",
    "ठीक है",
    "हम्म",
    "हम्म्म",
    "हम्म्म्म",
    "अछा",
    "अच्चा",
    "हां जी",
    "ओ के",
    "ओके",
)

GREETING_AGREEMENTS = ("hello", "hi", "namaste", "नमस्ते", "हेलो", "हैलो")
GREETING_PROTECT = True
SUSTAINED_SPEECH_SECS = 0.85
NO_TRANSCRIPT_LOG_SECS = 1.5
SMART_VAD_PARAMS = VADParams(confidence=0.75, min_volume=0.68)


class BargeInKind(Enum):
    INTERRUPT = "interrupt"
    IGNORE = "ignore"
    LONE_WORD = "lone_word"
    NO_WORDS = "no_words"


def _words(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text).lower()
    separated = "".join(
        character if unicodedata.category(character)[0] in "LMN" else " "
        for character in normalized
    )
    aliases = {
        "acha": "accha",
        "achha": "accha",
        "achcha": "accha",
        "अछा": "अच्छा",
        "अच्चा": "अच्छा",
        "हम्म्म": "हम्म",
        "हम्म्म्म": "हम्म",
    }
    words = []
    for word in separated.split():
        if re.fullmatch(r"hm{2,}", word):
            word = "hmm"
        words.append(aliases.get(word, word))
    return words


def _phrase_tokens(phrases: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(
        sorted((tuple(_words(phrase)) for phrase in phrases), key=len, reverse=True)
    )


_STOP_TOKENS = _phrase_tokens(STOP_PHRASES)
_AGREEMENT_TOKENS = _phrase_tokens(AGREEMENT_PHRASES)
_GREETING_TOKENS = _phrase_tokens(GREETING_AGREEMENTS)


def _contains_phrase(words: list[str], phrase: tuple[str, ...]) -> bool:
    length = len(phrase)
    return any(tuple(words[index : index + length]) == phrase for index in range(len(words)))


def _strip_phrases(
    words: list[str], phrases: tuple[tuple[str, ...], ...]
) -> list[str]:
    remaining: list[str] = []
    index = 0
    while index < len(words):
        matched = next(
            (
                phrase
                for phrase in phrases
                if tuple(words[index : index + len(phrase)]) == phrase
            ),
            None,
        )
        if matched:
            index += len(matched)
        else:
            remaining.append(words[index])
            index += 1
    return remaining


def classify(text: str, *, greeting: bool = False) -> BargeInKind:
    """Classify transcript text without retaining or logging the text."""
    words = _words(text)
    if not words:
        return BargeInKind.NO_WORDS
    if any(_contains_phrase(words, phrase) for phrase in _STOP_TOKENS):
        return BargeInKind.INTERRUPT

    agreements = _AGREEMENT_TOKENS + (_GREETING_TOKENS if greeting else ())
    remaining = _strip_phrases(words, agreements)
    if not remaining:
        return BargeInKind.IGNORE
    if len(remaining) == 1:
        return BargeInKind.LONE_WORD
    return BargeInKind.INTERRUPT


class BargeInTrace:
    """Per-call interruption timings shared by strategy, observer, and serializer."""

    def __init__(
        self,
        *,
        mode: str,
        conn_id: str | None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.mode = mode
        self.conn_id = conn_id if conn_id and re.fullmatch(r"[0-9a-f]{6}", conn_id) else "-"
        self.clock = clock
        self.vad_started_at: float | None = None
        self.fire_at: float | None = None
        self.clear_at: float | None = None
        self.cause: str | None = None
        self._logged = False
        self._measuring = False
        self._pending_cause: str | None = None
        self._bot_output_active = False
        self._first_audio_at: float | None = None
        self._last_audio_sent_at: float | None = None
        self._audio_duration_secs = 0.0

    def _reset_measurement(self) -> None:
        self.vad_started_at = None
        self.fire_at = None
        self.clear_at = None
        self.cause = None
        self._logged = False
        self._measuring = False
        self._pending_cause = None

    def _reset_playback(self) -> None:
        self._first_audio_at = None
        self._last_audio_sent_at = None
        self._audio_duration_secs = 0.0

    def note_bot_started(self) -> None:
        if not self._bot_output_active:
            self._reset_playback()
            self._reset_measurement()
        self._bot_output_active = True

    def note_bot_stopped(self) -> None:
        self._bot_output_active = False

    def note_audio_sent(self, byte_count: int) -> None:
        if self.mode != "smart" or byte_count <= 0:
            return
        now = self.clock()
        if self._first_audio_at is None:
            self._first_audio_at = now
        self._last_audio_sent_at = now
        self._audio_duration_secs += byte_count / (8000 * 2)

    def playback_end_at(self) -> float | None:
        if self.mode != "smart" or self._first_audio_at is None:
            return None
        duration_end = self._first_audio_at + self._audio_duration_secs
        return max(duration_end, self._last_audio_sent_at or duration_end)

    def playback_remaining(self) -> float:
        end_at = self.playback_end_at()
        return max(0.0, end_at - self.clock()) if end_at is not None else 0.0

    def is_bot_speaking(self) -> bool:
        if self._bot_output_active:
            return True
        end_at = self.playback_end_at()
        return end_at is not None and self.clock() < end_at

    def start_vad(self) -> None:
        self._reset_measurement()
        self.vad_started_at = self.clock()

    def arm(self, cause: str) -> None:
        self._pending_cause = cause

    def stamp_fire(self) -> None:
        if self.fire_at is not None and self.clear_at is None:
            return
        was_speaking = self.is_bot_speaking()
        self.fire_at = self.clock()
        self.clear_at = None
        self._logged = False
        self._measuring = was_speaking
        self.cause = self._pending_cause or (
            "legacy_vad" if self.vad_started_at is not None else "transcript"
        )
        self._pending_cause = None
        if was_speaking:
            self._bot_output_active = False
            self._reset_playback()
        else:
            self._reset_measurement()

    def stamp_clear_and_log(self) -> None:
        if self._logged or not self._measuring:
            return
        if self.fire_at is None:
            self.stamp_fire()
        if not self._measuring or self.fire_at is None:
            return
        self.clear_at = self.clock()
        reference = self.vad_started_at if self.vad_started_at is not None else self.fire_at
        t_fire_ms = max(0, int(round((self.fire_at - reference) * 1000)))
        t_clear_ms = max(t_fire_ms, int(round((self.clear_at - reference) * 1000)))
        logger.info(
            f"barge-in: conn={self.conn_id} mode={self.mode} cause={self.cause} "
            f"t_vad_ms={'0' if self.vad_started_at is not None else '-'} "
            f"t_fire_ms={t_fire_ms} t_clear_ms={t_clear_ms}"
        )
        self._logged = True
        self._measuring = False

    def log_ignored(self, kind: str, words: int) -> None:
        logger.info(
            f"barge-in ignored: conn={self.conn_id} kind={kind} words={max(0, words)}"
        )

    def log_no_transcript(self, vad_started_at: float) -> None:
        elapsed_ms = max(0, int(round((self.clock() - vad_started_at) * 1000)))
        logger.info(
            f"barge-in no-transcript: conn={self.conn_id} count=1 "
            f"t_vad_ms={elapsed_ms}"
        )

    def finish_burst(self) -> None:
        self._pending_cause = None


class SmartBargeInStartStrategy(BaseUserTurnStartStrategy):
    """Delay barge-in while the bot speaks until transcript intent is clear."""

    def __init__(
        self,
        *,
        trace: BargeInTrace,
        clock: Callable[[], float] = monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        **kwargs,
    ) -> None:
        super().__init__(enable_interruptions=True, **kwargs)
        self._trace = trace
        self._clock = clock
        self._sleep = sleep
        self._greeting_done = False
        self._greeting_lone_frame: TranscriptionFrame | None = None
        self._vad_started_at: float | None = None
        self._saw_transcript = False
        self._latest_kind = BargeInKind.NO_WORDS
        self._latest_word_count = 0
        self._ignored_logged = False
        self._interruption_fired = False
        self._pending_ignored: tuple[str, int] | None = None
        self._sustained_task: asyncio.Task | None = None
        self._no_transcript_task: asyncio.Task | None = None
        self._playback_end_task: asyncio.Task | None = None

    async def cleanup(self) -> None:
        self._flush_pending_ignored()
        await self._clear_burst()
        await self._cancel_playback_end_task()
        await super().cleanup()

    async def reset(self) -> None:
        await self._clear_burst()
        await self._cancel_playback_end_task()

    async def _cancel_sustained_task(self) -> None:
        task = self._sustained_task
        self._sustained_task = None
        if task and task is not asyncio.current_task() and not task.done():
            await self.cancel_task(task)

    async def _cancel_no_transcript_task(self) -> None:
        task = self._no_transcript_task
        self._no_transcript_task = None
        if task and task is not asyncio.current_task() and not task.done():
            await self.cancel_task(task)

    async def _cancel_playback_end_task(self) -> None:
        task = self._playback_end_task
        self._playback_end_task = None
        if task and task is not asyncio.current_task() and not task.done():
            await self.cancel_task(task)

    async def _clear_burst(self) -> None:
        await self._cancel_sustained_task()
        await self._cancel_no_transcript_task()
        self._vad_started_at = None
        self._saw_transcript = False
        self._latest_kind = BargeInKind.NO_WORDS
        self._latest_word_count = 0
        self._ignored_logged = False

    def _flush_pending_ignored(self) -> None:
        if self._pending_ignored:
            kind, word_count = self._pending_ignored
            self._trace.log_ignored(kind, word_count)
            self._pending_ignored = None

    async def _interrupt(self, cause: str) -> ProcessFrameResult:
        was_bot_speaking = self._trace.is_bot_speaking()
        self._interruption_fired = True
        self._trace.arm(cause)
        await self._cancel_no_transcript_task()
        await self._cancel_playback_end_task()
        await self.trigger_user_turn_started()
        if was_bot_speaking:
            await self._finish_greeting()
        return ProcessFrameResult.STOP

    async def _sustained_timer(self, delay: float) -> None:
        await self._sleep(delay)
        if (
            self._trace.is_bot_speaking()
            and self._greeting_done
            and self._vad_started_at is not None
            and self._latest_kind == BargeInKind.LONE_WORD
        ):
            await self._interrupt("sustained")

    def _arm_sustained_timer(self) -> None:
        if self._sustained_task or self._vad_started_at is None:
            return
        remaining = max(
            0.0,
            SUSTAINED_SPEECH_SECS - (self._clock() - self._vad_started_at),
        )
        self._sustained_task = self.create_task(self._sustained_timer(remaining))

    async def _no_transcript_timer(self, vad_started_at: float) -> None:
        await self._sleep(NO_TRANSCRIPT_LOG_SECS)
        if (
            self._vad_started_at == vad_started_at
            and not self._saw_transcript
            and self._trace.is_bot_speaking()
        ):
            self._trace.log_no_transcript(vad_started_at)

    def _arm_no_transcript_timer(self) -> None:
        if self._no_transcript_task or self._vad_started_at is None:
            return
        self._no_transcript_task = self.create_task(
            self._no_transcript_timer(self._vad_started_at)
        )

    async def _finish_greeting(self) -> None:
        if self._greeting_done:
            return
        self._greeting_done = True
        frame = self._greeting_lone_frame
        self._greeting_lone_frame = None
        if frame is not None:
            await self.push_frame(frame)

    async def _finish_audible_output(self) -> None:
        self._flush_pending_ignored()
        await self._clear_burst()
        self._interruption_fired = False
        self._trace.finish_burst()
        await self._finish_greeting()

    async def _playback_end_timer(self) -> None:
        await self._sleep(self._trace.playback_remaining())
        await self._finish_audible_output()

    def _arm_playback_end_timer(self) -> None:
        if self._playback_end_task:
            return
        self._playback_end_task = self.create_task(self._playback_end_timer())

    async def process_frame(self, frame: Frame) -> ProcessFrameResult:
        if isinstance(frame, BotStartedSpeakingFrame):
            await self._cancel_playback_end_task()
            self._trace.note_bot_started()
            return ProcessFrameResult.CONTINUE
        if isinstance(frame, BotStoppedSpeakingFrame):
            self._trace.note_bot_stopped()
            if self._trace.is_bot_speaking():
                self._arm_playback_end_timer()
            else:
                await self._finish_audible_output()
            return ProcessFrameResult.CONTINUE

        if not self._trace.is_bot_speaking():
            if isinstance(
                frame,
                (VADUserStartedSpeakingFrame, InterimTranscriptionFrame, TranscriptionFrame),
            ):
                return await self._interrupt(
                    "legacy_vad"
                    if isinstance(frame, VADUserStartedSpeakingFrame)
                    else "transcript"
                )
            return ProcessFrameResult.CONTINUE

        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._flush_pending_ignored()
            self._vad_started_at = self._clock()
            self._latest_kind = BargeInKind.NO_WORDS
            self._latest_word_count = 0
            self._saw_transcript = False
            self._ignored_logged = False
            self._interruption_fired = False
            self._trace.start_vad()
            self._arm_no_transcript_timer()
            return ProcessFrameResult.CONTINUE

        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if not self._interruption_fired and not self._ignored_logged:
                kind = (
                    "no_words"
                    if self._latest_kind == BargeInKind.NO_WORDS
                    else "single_word_pending"
                )
                self._pending_ignored = (kind, self._latest_word_count)
            await self._clear_burst()
            self._interruption_fired = False
            self._trace.finish_burst()
            return ProcessFrameResult.CONTINUE

        if not isinstance(frame, (InterimTranscriptionFrame, TranscriptionFrame)):
            return ProcessFrameResult.CONTINUE

        self._saw_transcript = True
        await self._cancel_no_transcript_task()
        self._pending_ignored = None
        greeting_protected = GREETING_PROTECT and not self._greeting_done
        kind = classify(frame.text, greeting=greeting_protected)
        self._latest_kind = kind
        self._latest_word_count = len(_words(frame.text))

        if kind == BargeInKind.INTERRUPT:
            return await self._interrupt(
                "stop_word"
                if any(_contains_phrase(_words(frame.text), phrase) for phrase in _STOP_TOKENS)
                else "multi_word"
            )
        if kind == BargeInKind.IGNORE:
            if isinstance(frame, TranscriptionFrame):
                await self.trigger_reset_aggregation()
                if not self._ignored_logged:
                    self._trace.log_ignored("agreement", self._latest_word_count)
                    self._ignored_logged = True
            return ProcessFrameResult.CONTINUE
        if kind == BargeInKind.LONE_WORD:
            if greeting_protected:
                if isinstance(frame, TranscriptionFrame):
                    await self.trigger_reset_aggregation()
                    self._greeting_lone_frame = frame
                return ProcessFrameResult.CONTINUE
            if isinstance(frame, TranscriptionFrame):
                return await self._interrupt("lone_word")
            self._arm_sustained_timer()
            return ProcessFrameResult.CONTINUE

        if kind == BargeInKind.NO_WORDS and isinstance(frame, TranscriptionFrame):
            await self.trigger_reset_aggregation()

        return ProcessFrameResult.CONTINUE


class BargeInObserver(BaseObserver):
    """Measure interruption fire and clear boundaries without transcript text."""

    def __init__(self, *, trace: BargeInTrace, user_aggregator, output_processor) -> None:
        super().__init__()
        self._trace = trace
        self._user_aggregator = user_aggregator
        self._output_processor = output_processor
        self._seen_vad: set[int] = set()
        self._seen_interruptions: set[int] = set()
        self._seen_bot_frames: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, BotStartedSpeakingFrame) and frame.id not in self._seen_bot_frames:
            self._seen_bot_frames.add(frame.id)
            self._trace.note_bot_started()
        elif isinstance(frame, BotStoppedSpeakingFrame) and frame.id not in self._seen_bot_frames:
            self._seen_bot_frames.add(frame.id)
            self._trace.note_bot_stopped()
        elif isinstance(frame, VADUserStartedSpeakingFrame) and frame.id not in self._seen_vad:
            self._seen_vad.add(frame.id)
            self._trace.start_vad()
        elif isinstance(frame, InterruptionFrame):
            if (
                data.source is self._user_aggregator
                and data.direction == FrameDirection.DOWNSTREAM
                and frame.id not in self._seen_interruptions
            ):
                self._seen_interruptions.add(frame.id)
                self._trace.stamp_fire()
            elif (
                self._trace.mode == "legacy"
                and data.source is self._output_processor
                and data.direction == FrameDirection.DOWNSTREAM
            ):
                self._trace.stamp_clear_and_log()


class DualKeyExotelSerializer(ExotelFrameSerializer):
    """Send both documented and Pipecat Exotel stream-id keys in smart mode."""

    def __init__(self, *args, trace: BargeInTrace, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._trace = trace

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            answer = {
                "event": "clear",
                "stream_sid": self._stream_sid,
                "streamSid": self._stream_sid,
            }
            self._trace.stamp_clear_and_log()
            return json.dumps(answer)

        serialized = await super().serialize(frame)
        if isinstance(frame, AudioRawFrame) and isinstance(serialized, str):
            answer = json.loads(serialized)
            payload = base64.b64decode(answer["media"]["payload"])
            self._trace.note_audio_sent(len(payload))
            answer["stream_sid"] = self._stream_sid
            return json.dumps(answer)
        return serialized
