# A cold ElevenLabs voice costs about 640 ms on the first call after a quiet spell

- Greeting text-to-speech first audio was 744 ms and 802 ms on the two cold calls of 2026-10-24 (before and after 015), against about 160 ms on warm calls, so a cold voice costs about 640 ms. After 13 idle hours (2026-10-23) it was 1,582 ms.
- After 015 our server spends 0.5 to 1.2 s from `ws_connected` to the first audio, so this is now the largest start-up lever we control.
- Candidate: a keep-warm request on a timer so the first caller after a quiet spell finds the voice warm. UNVERIFIED: whether the warm state belongs to the voice, the model or the connection, how long it lasts, and what the keep-warm requests cost in characters.
- Source: founder's 015 exit test and before-run, 2026-10-24 (`log.md`); `docs/baselines/2026-10-23-011-exit.md` for the 13-hour case.
