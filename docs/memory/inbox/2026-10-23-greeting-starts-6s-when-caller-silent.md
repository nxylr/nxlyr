# With the caller silent the greeting starts about 6 s after pickup

- A caller who says hello first is answered in 2.5 to 3 s with no second greeting; a caller who waits in silence hears the greeting at about 6 s. Unexplained: the greeting's own TTS takes about 160 ms, so the time goes before the pipeline's clock starts.
- Task L1 must log pickup, WebSocket connect, greeting queued and first audio sent, and test both cases.
- Source: founder stopwatch and note, `docs/baselines/2026-10-23-011-exit.md`.
