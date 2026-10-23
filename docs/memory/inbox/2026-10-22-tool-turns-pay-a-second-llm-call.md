# Tool turns pay a second LLM call

- A turn that uses a tool makes a second LLM call after it: median 631 ms in the baseline, 640 ms in the 011 exit test. 19 of 92 exit turns (21%) used a tool; tool turns p50 2,091 ms, p95 2,613 ms, now the slowest turns.
- Belongs to task 008 and prompt v2, not 011.
- Source: events log, baseline 2026-10-22 and 011 exit test 2026-10-23 (`docs/baselines/2026-10-23-011-exit.md`).
