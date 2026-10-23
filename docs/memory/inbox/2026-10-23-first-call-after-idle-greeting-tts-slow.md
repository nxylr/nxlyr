# The first call after 13 idle hours had a slow greeting TTS

- Greeting TTS first audio was 1,582 ms on call 1 against about 160 ms on later calls, and its slowest turn was 3,170 ms without a tool. A cold first call is still slow (task L1).
- Source: `docs/baselines/2026-10-23-011-exit.md` (call 1, instance #2, container up 13 h before the batch).
