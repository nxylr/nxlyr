"""
Week 2 latency recorder for the NXLYR test pipeline.  (Pipecat 1.5.0)

v2 — wraps Pipecat's own UserBotLatencyObserver instead of re-deriving turn
boundaries from raw VAD frames.

Why the rewrite: v1 treated every VADUserStoppedSpeakingFrame as a turn
boundary. In 1.5.0's turn architecture, VAD fires a "stopped speaking" event
on *any* pause (including mid-sentence pauses while you're thinking) — a
separate turn analyzer decides whether that pause is a real end-of-turn.
That's why v1's CSV showed several blank-roundtrip rows before one real one:
each new VAD stop was closing the previous (incomplete) "turn" early.

UserBotLatencyObserver already solves this correctly: it resets on
VADUserStartedSpeakingFrame and only finalizes on BotStartedSpeakingFrame,
using the framework's real turn-completion signal. We just tap its events:
  - on_latency_measured   -> authoritative round-trip (seconds, one float)
  - on_latency_breakdown  -> per-service TTFB + turn duration for that cycle
  - on_first_bot_speech_latency -> handles the opening greeting, which has
    no preceding user turn and so may not fire on_latency_measured

--- Wiring (in test_pipeline.py) -----------------------------------------

    from week2_latency_observer import make_week2_latency_observer

    latency_observer = make_week2_latency_observer("week2_latency.csv")

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,        # REQUIRED for the breakdown data
            enable_usage_metrics=True,
        ),
        observers=[latency_observer],   # pass the returned instance directly
    )

This replaces the old `Week2LatencyRecorder(...)` instantiation — the new
entry point is a factory function, not a class you construct yourself,
because UserBotLatencyObserver owns the event-handler decorator pattern.
--------------------------------------------------------------------------
"""

import csv
import os
import re

from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver

_SECONDS_TO_MS = 1000.0

# Confirmed against real output from chronological_events(), e.g.:
#   "DeepgramSTTService#0: TTFB 0.536s"
#   "OpenAILLMService#0: TTFB 0.826s"
#   "ElevenLabsTTSService#0: TTFB 0.210s"
# We parse these strings directly rather than guessing attribute names on
# the underlying TTFBBreakdownMetrics objects, since the text format is
# proven and the object's field names weren't.
_TTFB_LINE_RE = re.compile(r"^(?P<proc>.+?):\s*TTFB\s+(?P<val>[\d.]+)s\s*$")


def _classify(name: str):
    # Check specific provider names first (unambiguous). Falling back to the
    # generic stt/llm/tts abbreviations is collision-prone: "DeepgramSTTService"
    # and "ElevenLabsTTSService" each accidentally contain "tts"/"stt" as a
    # substring where the abbreviation runs into "...Service".
    n = (name or "").lower()
    if "deepgram" in n:
        return "stt_ttfb_ms"
    if "openai" in n or "gpt" in n:
        return "llm_ttfb_ms"
    if "elevenlabs" in n:
        return "tts_ttfb_ms"
    if "stt" in n:
        return "stt_ttfb_ms"
    if "llm" in n:
        return "llm_ttfb_ms"
    if "tts" in n:
        return "tts_ttfb_ms"
    return None


def make_week2_latency_observer(csv_path="week2_latency.csv", log_path=None):
    """Build a UserBotLatencyObserver wired to write one CSV row per turn.

    Returns the observer instance — pass it directly in PipelineTask(observers=[...]).
    """
    log_path = log_path or (os.path.splitext(csv_path)[0] + "_events.log")

    fields = ["turn", "stt_ttfb_ms", "llm_ttfb_ms", "tts_ttfb_ms",
              "roundtrip_ms", "user_turn_secs"]
    new_file = not os.path.exists(csv_path)

    # Continue the turn counter from wherever the file left off, instead of
    # resetting to 0 each process start. If turns reset to 1 every run and
    # you append multiple runs into one CSV (as the Week 2 protocol does),
    # the label stops being a unique key — turn 19 from run 1 and turn 19
    # from run 3 become indistinguishable without re-deriving order from
    # file position. Starting from the last seen turn avoids that entirely.
    last_turn = 0
    if not new_file:
        try:
            with open(csv_path, newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        last_turn = max(last_turn, int(row["turn"]))
                    except (KeyError, ValueError):
                        pass
        except Exception:
            pass

    csv_fh = open(csv_path, "a", newline="")
    writer = csv.DictWriter(csv_fh, fieldnames=fields)
    if new_file:
        writer.writeheader()
        csv_fh.flush()
    log_fh = open(log_path, "a")

    state = {"turn": last_turn, "pending": None}

    def _new_pending():
        state["turn"] += 1
        return {"turn": state["turn"]}

    def _flush():
        row = state["pending"]
        state["pending"] = None
        if row is None:
            return
        out = {k: row.get(k, "") for k in fields}
        writer.writerow(out)
        csv_fh.flush()
        print(
            f"[turn {out['turn']:>2}]  "
            f"STT={out['stt_ttfb_ms'] or '-'}ms  "
            f"LLM={out['llm_ttfb_ms'] or '-'}ms  "
            f"TTS={out['tts_ttfb_ms'] or '-'}ms  "
            f"ROUNDTRIP={out['roundtrip_ms'] or '-'}ms"
        )

    observer = UserBotLatencyObserver()

    @observer.event_handler("on_latency_measured")
    async def _on_measured(obs, latency):
        p = state["pending"] or _new_pending()
        p["roundtrip_ms"] = round(latency * _SECONDS_TO_MS, 1)
        p["_measured"] = True
        state["pending"] = p
        if p.get("_breakdown"):
            _flush()

    @observer.event_handler("on_latency_breakdown")
    async def _on_breakdown(obs, breakdown):
        p = state["pending"] or _new_pending()

        uts = getattr(breakdown, "user_turn_secs", None)
        if uts is not None:
            p["user_turn_secs"] = round(uts, 3)

        try:
            events = list(breakdown.chronological_events())
        except Exception as e:
            events = []
            log_fh.write(f"[turn {p['turn']}] <could not read events: {e}>\n")

        for raw in events:
            line = str(raw).strip()
            log_fh.write(f"[turn {p['turn']}] {line}\n")
            m = _TTFB_LINE_RE.match(line)
            if m:
                col = _classify(m.group("proc"))
                if col:
                    p[col] = round(float(m.group("val")) * _SECONDS_TO_MS, 1)
        log_fh.flush()

        p["_breakdown"] = True
        state["pending"] = p
        if p.get("_measured"):
            _flush()

    @observer.event_handler("on_first_bot_speech_latency")
    async def _on_first_speech(obs, latency):
        # The opening greeting has no preceding user turn, so it may not
        # trigger on_latency_measured. If a breakdown arrived for it but
        # nothing has flushed yet, close it out here instead of hanging.
        p = state["pending"]
        if p is not None and p.get("_breakdown") and not p.get("_measured"):
            p["roundtrip_ms"] = round(latency * _SECONDS_TO_MS, 1)
            p["_measured"] = True
            _flush()

    return observer
