# The greeting loses about 3 s before synthesis starts

- Greeting TTS first audio is about 160 ms on warm calls, yet pickup to first word took 3.0 to 4.9 s in the baseline. The time goes before the pipeline's clock starts.
- Source: founder stopwatch, baseline 2026-10-22 (calls 1, 4, 7, 10: 3.0, 3.75, 4.9, 3.8 s); `docs/baselines/2026-10-23-011-exit.md`.
