# Tool turns pay a second LLM call

- A turn that uses a tool makes a second LLM call after it: median 631 ms in the baseline, 640 ms in the 011 exit test. 19 of 92 exit turns (21%) used a tool; tool turns p50 2,091 ms, p95 2,613 ms, now the slowest turns.
- Belongs to task 008 and prompt v2, not 011.
- Source: events log, baseline 2026-10-22 and 011 exit test 2026-10-23 (`docs/baselines/2026-10-23-011-exit.md`).
- Update 2026-10-27 (task 008, PR #46): the second call is removed on failure and refusal turns (fixed sentence from code, `run_llm=False`) and kept on success turns (spec Q4 option A). A fixed success sentence (option C) is a separate, undecided item; decide it from 008's live-call numbers. Not measured by an agent.
