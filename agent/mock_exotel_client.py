#!/usr/bin/env python3
"""
NXLYR — mock Exotel media-stream client (Week 3 / Task 3.1)

Stands in for Exotel's App Bazaar "Voicebot" applet so bot.py's telephony path
can be exercised end-to-end without an Exotel account, a phone number, or a
billable call. Talks raw `websockets` — deliberately no pipecat import, so that
a bug in our understanding of the protocol shows up as a failed call rather than
being papered over by using the same serializer on both ends.

The wire format below was read off the installed pipecat-ai 1.5.0 sources, not
off Exotel's docs — what matters is what bot.py will actually accept:

  pipecat/runner/utils.py :: parse_telephony_websocket()
      Consumes exactly TWO text messages before returning, then hands the socket
      to the transport. So we send exactly two: `connected`, then `start`.

      Exotel is auto-detected (utils.py:96-105) only when a message has
      event == "start" AND its "start" object carries all three of
      "stream_sid", "call_sid", "account_sid". Drop any one of them and
      detection falls through to "unknown" and bot.py raises. Note these are
      snake_case — Twilio's variant of this same protocol is camelCase, and the
      detector distinguishes the two providers purely on that.

  pipecat/serializers/exotel.py :: ExotelFrameSerializer
      deserialize() handles ONLY "media" and "dtmf". Every other event —
      including "stop" — falls off the end and returns None, silently.
      media.payload is base64 of raw 16-bit signed little-endian PCM, mono,
      8 kHz. There is NO mu-law step: the Exotel serializer resamples the
      decoded bytes directly, unlike twilio.py which calls ulaw_to_pcm() first.
      Since bot.py pins the pipeline to 8000 Hz too, the resample is a literal
      passthrough (soxr_stream_resampler.py:110).

      serialize() emits {"event": "media", "streamSid": ..., "media":
      {"payload": ...}} — camelCase OUTBOUND against snake_case INBOUND.

      OPEN QUESTION — do not read this asymmetry as Exotel's protocol. Exotel's
      own docs (the article exotel.py:37 links to) specify "stream_sid",
      snake_case, in BOTH directions; their media event is explicitly labelled
      as shared between them. pipecat's outbound camelCase contradicts that.
      twilio.py:187,203 emits the identical camelCase keys and Twilio's real
      protocol IS camelCase, so this looks like exotel.py was derived from
      twilio.py without converting the outbound key — the inbound side lives in
      runner/utils.py, was written separately, and is correctly snake_case.
      Nothing is reported upstream (searched pipecat-ai issues + PRs) and main
      still has it as of 2026-08-04.

      This client CANNOT settle the question: it never reads the field (see
      receive_loop — only `event` and `media.payload` are used; streamSid
      appears once, in a log line). Only a real Exotel call can show whether
      Exotel ignores the unknown key and plays the audio, or drops the frame
      and the caller hears silence. Resolve upstream or with a narrow override
      at our call site; do not patch the installed library.

  Chunk sizes — same doc: payloads must be "multiples of 320 bytes", minimum
      "3.2k (100ms data)". pipecat sends 640-byte chunks outbound
      (audio_out_10ms_chunks=4 at 8 kHz) and this client sends 320-byte chunks
      inbound; both are valid multiples but under that stated minimum. The
      minimum is ambiguous in Exotel's wording (3.2 kB is 200 ms at 8 kHz, not
      100 ms, so it may be written for the 16 kHz case). FastAPIWebsocketParams
      has `fixed_audio_packet_size` for exactly this and bot.py does not set it.
      Also unresolved until a real call.

Two consequences that shape this client:

  1. "stop" does not end the call. Nothing in the pipeline reacts to it. The
     only thing that tears bot.py down is the socket actually closing:
     _WebSocketMessageIterator sees websocket.disconnect -> StopAsyncIteration
     -> trigger_client_disconnected() (fastapi.py:388-390) -> bot.py's
     on_client_disconnected -> worker.cancel(). So we always close after stop.
     bot.py sets no session_timeout, so there is no backstop if we don't.

  2. A real phone line carries continuous audio, and the pipeline depends on
     that: Silero VAD and Deepgram's endpointing=300 both need to *hear* the
     silence after an utterance to decide the turn ended. Going quiet by simply
     not sending packets is not the same thing. So we keep streaming silence
     frames at the same cadence during every pause — before the WAV, and after
     it while the bot replies.

Usage:
    python mock_exotel_client.py --wav phrase_8k.wav
    python mock_exotel_client.py --wav t1.wav --wav t2.wav --wav t3.wav   # 3 turns
    python mock_exotel_client.py --wav phrase_8k.wav --mode abrupt --abrupt-after 2.0

Repeat --wav to hold a multi-turn conversation: each file is one user utterance,
and the client waits for the bot's reply before starting the next one.

Input WAV must be 8 kHz, mono, 16-bit PCM. To make one on macOS with no extra
dependencies:
    say -v Rishi -o /tmp/p.aiff "your test phrase here"
    afconvert -f WAVE -d LEI16@8000 -c 1 /tmp/p.aiff phrase_8k.wav
"""

import argparse
import asyncio
import base64
import contextlib
import json
import sys
import time
import wave
from dataclasses import dataclass, field

import websockets
from websockets.asyncio.client import connect

EXOTEL_SAMPLE_RATE = 8000
SAMPLE_WIDTH = 2  # 16-bit signed LE, per ExotelFrameSerializer
CHANNELS = 1


# ----------------- state shared between the send and receive tasks ----------------- #


@dataclass
class CallState:
    """Everything the two concurrent tasks need to see about each other."""

    t0: float = field(default_factory=time.monotonic)
    stream_sid: str = ""

    # Captured from the bot. Kept as a list of chunks and joined once at the end
    # rather than concatenated per-message, so a long call doesn't turn into
    # quadratic bytes copying.
    inbound_audio: list[bytes] = field(default_factory=list)
    inbound_media_count: int = 0
    inbound_bytes: int = 0
    first_inbound_media_at: float | None = None
    last_inbound_media_at: float | None = None

    # Non-media events the bot sent us, e.g. {"event": "clear"} on interruption.
    # bot.py disables interruptions, so anything here is worth reading.
    other_events: list[dict] = field(default_factory=list)

    outbound_media_count: int = 0
    sequence_number: int = 0

    # Bytes of bot audio attributable to each user turn, in order.
    turn_replies: list[int] = field(default_factory=list)

    def elapsed(self) -> float:
        return time.monotonic() - self.t0

    def next_seq(self) -> int:
        self.sequence_number += 1
        return self.sequence_number


def log(state: CallState, msg: str) -> None:
    """Timestamped against connect, so output lines up with the container logs."""
    print(f"[{state.elapsed():7.3f}s] {msg}", flush=True)


# ----------------- WAV in / WAV out ----------------- #


def read_wav_8k_mono(path: str) -> bytes:
    """Read a WAV and return its raw PCM, refusing anything the bot can't use.

    Refuses rather than silently resampling: a resample here would hide a
    format mismatch that would be a real bug against a real Exotel stream.
    """
    with wave.open(path, "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())

    problems = []
    if channels != CHANNELS:
        problems.append(f"{channels} channels (need {CHANNELS})")
    if width != SAMPLE_WIDTH:
        problems.append(f"{width * 8}-bit samples (need {SAMPLE_WIDTH * 8}-bit)")
    if rate != EXOTEL_SAMPLE_RATE:
        problems.append(f"{rate} Hz (need {EXOTEL_SAMPLE_RATE} Hz)")

    if problems:
        raise SystemExit(
            f"{path} is not an Exotel-shaped WAV: {', '.join(problems)}.\n"
            f"Convert it with:\n"
            f"  afconvert -f WAVE -d LEI16@8000 -c 1 {path} converted_8k.wav\n"
            f"or, with ffmpeg:\n"
            f"  ffmpeg -i {path} -ar 8000 -ac 1 -c:a pcm_s16le converted_8k.wav"
        )

    return frames


def write_wav_8k_mono(path: str, pcm: bytes) -> None:
    with wave.open(path, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(EXOTEL_SAMPLE_RATE)
        wav.writeframes(pcm)


# ----------------- outbound: handshake, media, stop ----------------- #


async def send_handshake(ws, state: CallState, args) -> None:
    """Send the two messages parse_telephony_websocket() reads.

    Order matters. The detector tries the first message, then the second
    (utils.py:214-221); `connected` carries no identifiers and detects as
    "unknown", so `start` must be the second message, not the first.
    """
    connected = {"event": "connected"}
    await ws.send(json.dumps(connected))
    log(state, f"-> connected  {json.dumps(connected)}")

    start = {
        "event": "start",
        "sequence_number": str(state.next_seq()),
        # Real Exotel repeats the sid at the top level as well as inside `start`.
        # Only the nested copy is read (utils.py:262-270); this one is here so the
        # message on the wire matches what the bot will see in production.
        "stream_sid": args.stream_sid,
        "start": {
            "stream_sid": args.stream_sid,
            "call_sid": args.call_sid,
            "account_sid": args.account_sid,
            "from": args.from_number,
            "to": args.to_number,
            "custom_parameters": {},
            # media_format is not read by the Exotel path at all — included
            # because a real stream carries it and its absence should never be
            # what makes a test pass.
            "media_format": {
                "encoding": "base64",
                "sample_rate": EXOTEL_SAMPLE_RATE,
                "bit_rate": "16kbps",
            },
        },
    }
    await ws.send(json.dumps(start))
    log(state, f"-> start      stream_sid={args.stream_sid} call_sid={args.call_sid}")


async def send_media(ws, state: CallState, pcm_chunk: bytes) -> None:
    """One media event. Only media.payload is read; the rest mirrors a real stream."""
    seq = state.next_seq()
    message = {
        "event": "media",
        "sequence_number": str(seq),
        "stream_sid": state.stream_sid,
        "media": {
            "chunk": str(state.outbound_media_count + 1),
            "timestamp": str(int(state.elapsed() * 1000)),
            "payload": base64.b64encode(pcm_chunk).decode("ascii"),
        },
    }
    await ws.send(json.dumps(message))
    state.outbound_media_count += 1


async def send_stop(ws, state: CallState, args) -> None:
    """Send `stop`. Cosmetic on its own — the close that follows is what ends the call."""
    message = {
        "event": "stop",
        "sequence_number": str(state.next_seq()),
        "stream_sid": args.stream_sid,
        "stop": {
            "call_sid": args.call_sid,
            "account_sid": args.account_sid,
            "reason": "callended",
        },
    }
    await ws.send(json.dumps(message))
    log(state, f"-> stop       {json.dumps(message['stop'])}")


# ----------------- the paced audio clock ----------------- #


class Pacer:
    """Real-time cadence for outgoing media, on one clock for the whole call.

    Deadlines are computed from a fixed origin rather than by sleeping
    chunk_ms between sends: the latter accumulates every scheduling delay and
    the stream drifts slower than real time, which would quietly change what
    the VAD sees.
    """

    def __init__(self, chunk_seconds: float):
        self._chunk_seconds = chunk_seconds
        self._origin = time.monotonic()
        self._sent = 0

    async def wait_for_next(self) -> None:
        deadline = self._origin + self._sent * self._chunk_seconds
        delay = deadline - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        self._sent += 1


async def stream_silence(
    ws,
    state: CallState,
    pacer: Pacer,
    silence_chunk: bytes,
    duration: float,
    *,
    until_quiet_for: float | None = None,
    baseline_media_count: int = 0,
) -> None:
    """Hold the line open with silence — what a real caller not-talking sounds like.

    With `until_quiet_for`, `duration` becomes a ceiling: we stop early once the
    bot has sent audio and then gone quiet for that long, i.e. it finished
    speaking. That keeps the wait self-adjusting instead of hard-coding a guess
    at how long an LLM-generated reply takes to say.

    `baseline_media_count` is what makes that safe across turns. Without it the
    check reads `last_inbound_media_at` left over from the PREVIOUS reply, finds
    it already older than `until_quiet_for`, and returns after a single 20ms
    chunk — so the next utterance starts before the bot has had any chance to
    answer. Requiring the count to advance first means "quiet" can only mean
    "quiet since this turn's audio", never "quiet since some earlier turn".
    """
    deadline = time.monotonic() + duration

    while time.monotonic() < deadline:
        await pacer.wait_for_next()
        await send_media(ws, state, silence_chunk)

        if until_quiet_for is None:
            continue
        # The bot has not started responding to THIS turn yet.
        if state.inbound_media_count <= baseline_media_count:
            continue
        if state.last_inbound_media_at is None:
            continue
        if time.monotonic() - state.last_inbound_media_at >= until_quiet_for:
            return


async def stream_wav(
    ws,
    state: CallState,
    pacer: Pacer,
    pcm: bytes,
    chunk_bytes: int,
    *,
    abort_after: float | None = None,
) -> bool:
    """Stream the WAV at real-time pace. Returns True if it was cut short."""
    started = time.monotonic()

    for offset in range(0, len(pcm), chunk_bytes):
        if abort_after is not None and (time.monotonic() - started) >= abort_after:
            return True

        chunk = pcm[offset : offset + chunk_bytes]
        # Final partial chunk: pad to full length. The serializer accepts any
        # payload size, but a short frame is not something a real carrier emits.
        if len(chunk) < chunk_bytes:
            chunk = chunk + b"\x00" * (chunk_bytes - len(chunk))

        await pacer.wait_for_next()
        await send_media(ws, state, chunk)

    return False


# ----------------- inbound: capture whatever the bot says ----------------- #


async def receive_loop(ws, state: CallState) -> None:
    """Drain the socket for the life of the call, keeping every audio payload.

    Runs concurrently with sending — the bot starts talking the moment it sees
    the connection (bot.py's on_client_connected queues an LLMRunFrame), which
    is well before we've finished streaming.
    """
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                # The serializer only ever emits JSON text. Binary here means our
                # model of the protocol is wrong, so say so rather than ignore it.
                log(state, f"<- BINARY frame, {len(raw)} bytes (unexpected)")
                continue

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                log(state, f"<- non-JSON text: {raw[:200]!r}")
                continue

            event = message.get("event")

            if event == "media":
                payload = message.get("media", {}).get("payload", "")
                audio = base64.b64decode(payload)
                state.inbound_audio.append(audio)
                state.inbound_bytes += len(audio)
                state.inbound_media_count += 1
                state.last_inbound_media_at = time.monotonic()

                if state.first_inbound_media_at is None:
                    state.first_inbound_media_at = state.last_inbound_media_at
                    log(
                        state,
                        f"<- first media from bot "
                        f"(streamSid={message.get('streamSid')}, {len(audio)} bytes)",
                    )
            else:
                state.other_events.append(message)
                log(state, f"<- {event}: {json.dumps(message)[:300]}")

    except websockets.exceptions.ConnectionClosedOK:
        log(state, "<- socket closed cleanly by bot")
    except websockets.exceptions.ConnectionClosedError as exc:
        log(state, f"<- socket closed with error: {exc}")


# ----------------- the call ----------------- #


async def run_call(args) -> int:
    turns = [(path, read_wav_8k_mono(path)) for path in args.wav]

    chunk_bytes = int(EXOTEL_SAMPLE_RATE * args.chunk_ms / 1000) * SAMPLE_WIDTH
    chunk_seconds = args.chunk_ms / 1000
    silence_chunk = b"\x00" * chunk_bytes

    for index, (path, pcm) in enumerate(turns, start=1):
        seconds = len(pcm) / (EXOTEL_SAMPLE_RATE * SAMPLE_WIDTH)
        print(f"Turn {index}  : {path} ({seconds:.2f}s, {len(pcm)} bytes PCM)")
    print(f"Chunking: {args.chunk_ms}ms = {chunk_bytes} bytes/event, real-time pace")
    print(f"Mode    : {args.mode}")
    print(f"Connect : {args.url}")
    print("-" * 72)

    state = CallState()
    state.stream_sid = args.stream_sid  # read by send_media

    aborted = False
    receiver: asyncio.Task | None = None

    try:
        async with connect(args.url, max_size=None) as ws:
            state.t0 = time.monotonic()
            log(state, "connected")

            receiver = asyncio.create_task(receive_loop(ws, state))
            pacer = Pacer(chunk_seconds)

            await send_handshake(ws, state, args)

            # Let the bot get its greeting out before we talk over it. bot.py
            # runs with interruptions disabled, so overlapping speech wouldn't
            # stop the greeting — it would just get transcribed on top of it and
            # muddy the one thing this test is trying to observe.
            if args.greeting_wait != 0:
                log(state, f"streaming silence, waiting for greeting (max {args.greeting_wait}s)")
                await stream_silence(
                    ws,
                    state,
                    pacer,
                    silence_chunk,
                    args.greeting_wait,
                    until_quiet_for=args.greeting_gap,
                )
                if state.inbound_media_count == 0:
                    log(state, "WARNING: bot sent no audio during the greeting window")
                else:
                    log(state, f"greeting done ({state.inbound_bytes} bytes received)")

            for index, (path, pcm) in enumerate(turns, start=1):
                seconds = len(pcm) / (EXOTEL_SAMPLE_RATE * SAMPLE_WIDTH)
                log(state, f"turn {index}/{len(turns)}: streaming {path} ({seconds:.2f}s)")

                abrupt_here = args.mode == "abrupt" and index == args.abrupt_turn
                aborted = await stream_wav(
                    ws,
                    state,
                    pacer,
                    pcm,
                    chunk_bytes,
                    abort_after=args.abrupt_after if abrupt_here else None,
                )
                if aborted:
                    break

                # Measure the reply per turn rather than only in aggregate — a
                # pipeline that answers turn 1 and then goes deaf looks identical
                # to a healthy one in a single total-bytes number.
                before = state.inbound_bytes
                await stream_silence(
                    ws,
                    state,
                    pacer,
                    silence_chunk,
                    args.linger,
                    until_quiet_for=args.reply_gap,
                    baseline_media_count=state.inbound_media_count,
                )
                reply_bytes = state.inbound_bytes - before
                reply_seconds = reply_bytes / (EXOTEL_SAMPLE_RATE * SAMPLE_WIDTH)
                state.turn_replies.append(reply_bytes)
                log(state, f"turn {index}: reply {reply_seconds:.2f}s ({reply_bytes} bytes)")

            if aborted:
                # 3.3: vanish mid-sentence. transport.abort() drops the TCP
                # connection with no close frame and no `stop` — the closest
                # thing to a carrier dropping the leg. A plain ws.close() would
                # be a clean shutdown and would not test the same path.
                log(state, f"ABRUPT: aborting socket after {args.abrupt_after}s, no stop event")
                ws.transport.abort()
            else:
                log(state, "all turns done, hanging up")
                await send_stop(ws, state, args)
                # `stop` is a no-op inside the serializer; this close is what
                # actually ends the call for bot.py.
                log(state, "closing socket")
                await ws.close()

            if receiver:
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(receiver), timeout=5)

    except OSError as exc:
        print(f"\nCould not connect to {args.url}: {exc}", file=sys.stderr)
        return 1
    except websockets.exceptions.InvalidStatus as exc:
        print(f"\nServer rejected the WebSocket upgrade: {exc}", file=sys.stderr)
        return 1
    finally:
        if receiver and not receiver.done():
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver

        # Written in `finally` so an abrupt run still leaves behind whatever the
        # bot managed to say before we pulled the plug.
        captured = b"".join(state.inbound_audio)
        if captured:
            write_wav_8k_mono(args.out, captured)

    # ----------------- summary ----------------- #

    captured = b"".join(state.inbound_audio)
    captured_seconds = len(captured) / (EXOTEL_SAMPLE_RATE * SAMPLE_WIDTH)

    print("-" * 72)
    print(f"Sent     : {state.outbound_media_count} media events")
    print(f"Received : {state.inbound_media_count} media events, {state.inbound_bytes} bytes")

    for index, reply_bytes in enumerate(state.turn_replies, start=1):
        seconds = reply_bytes / (EXOTEL_SAMPLE_RATE * SAMPLE_WIDTH)
        verdict = "OK" if reply_bytes else "SILENT"
        print(f"  turn {index} reply: {seconds:6.2f}s  {reply_bytes:8} bytes  {verdict}")
    print(f"Audio out: {captured_seconds:.2f}s -> {args.out}" if captured else "Audio out: NONE")

    if state.first_inbound_media_at is not None:
        print(f"First bot audio at +{state.first_inbound_media_at - state.t0:.3f}s")

    if state.other_events:
        print(f"Non-media events from bot: {len(state.other_events)}")
        for event in state.other_events:
            print(f"  {json.dumps(event)[:200]}")

    if not captured:
        print("\nNo audio came back. The bot accepted the socket but never spoke —")
        print("check the container logs for a traceback or a missing API key.")
        return 1

    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Mock Exotel media stream for testing bot.py's telephony path.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--url", default="ws://localhost:7860/ws", help="bot WebSocket URL")
    parser.add_argument(
        "--wav",
        required=True,
        action="append",
        help="input WAV: 8 kHz, mono, 16-bit PCM. Repeat for a multi-turn conversation",
    )
    parser.add_argument("--out", default="mock_exotel_out.wav", help="where to write bot audio")

    parser.add_argument(
        "--mode",
        choices=["normal", "abrupt"],
        default="normal",
        help="normal: stream, linger, stop, close. abrupt: drop the TCP connection mid-WAV",
    )
    parser.add_argument(
        "--abrupt-after",
        type=float,
        default=2.0,
        help="seconds into the WAV to drop the connection (--mode abrupt only)",
    )
    parser.add_argument(
        "--abrupt-turn",
        type=int,
        default=1,
        help="which turn to drop the connection during (--mode abrupt only)",
    )

    parser.add_argument(
        "--chunk-ms", type=int, default=20, help="audio per media event, milliseconds"
    )
    parser.add_argument(
        "--greeting-wait",
        type=float,
        default=20.0,
        help="max seconds of silence to send before speaking, letting the bot greet. 0 disables",
    )
    parser.add_argument(
        "--greeting-gap",
        type=float,
        default=1.2,
        help="treat the greeting as finished after this many seconds of bot silence",
    )
    parser.add_argument(
        "--linger",
        type=float,
        default=30.0,
        help="max seconds to hold the line open after the WAV, waiting for the reply",
    )
    parser.add_argument(
        "--reply-gap",
        type=float,
        default=2.0,
        help="treat the reply as finished after this many seconds of bot silence",
    )

    parser.add_argument("--stream-sid", default="mockstream00000000000000000001")
    parser.add_argument("--call-sid", default="mockcall00000000000000000000001")
    parser.add_argument("--account-sid", default="mockaccount000000000000000001")
    parser.add_argument("--from-number", dest="from_number", default="+919000000001")
    parser.add_argument("--to-number", dest="to_number", default="+919000000002")

    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(run_call(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
