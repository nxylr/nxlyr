# First-sentence wait went 74 ms, 76 ms, then 145 ms

- First-sentence wait p50: 74 ms (22 Oct baseline), 76 ms (011 exit), 145 ms (014 exit, Part A, 109 user turns). The 014 gate was 84 ms; LLM first token p50 was 726 ms against a gate of 716 ms.
- Hypothesis (UNVERIFIED): banning filler openers removed a cheap two-token first sentence, so TTS now waits for a substantive one. Prediction to test in v2.1: allowing short connectives brings it back under 100 ms. This is why no latency rerun was run.
- Rejected as a fix: Pipecat's TOKEN text aggregation would cut the wait to near zero but sends fragments to TTS (see `2026-10-24-elevenlabs-voice-settings-unverified-on-flash.md`).
- Source: founder, `latency_report.py` on Part A of the 014 exit test, 2026-10-24.
