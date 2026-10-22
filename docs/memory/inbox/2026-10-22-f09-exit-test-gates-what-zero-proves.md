# F09: what the exit-test counts prove, and what they do not

- Counts come from `docker logs nxlyr_agent --since <T0>` over a batch of N real calls (Batch A on the old code before any container recreate, Batch B after deploy). Two controls make a 0 meaningful: the window has lines, and `Call finished` is at least N.
- A zero count proves that, in that window, no line contains `redis://`, `BasicAuth`, `Bearer `, a Telegram-shaped token (`bot[0-9]{6,}:[A-Za-z0-9_-]{20,}`), `eyJ`, `Generating chat from context`, or the last 6 digits of the founder's own number as one contiguous run.
- It does **not** prove: that other phone formats are absent (spaced, grouped, spoken, landline-style such as `02212345678`); that anyone else's number is masked (only the founder's is searched); anything outside the window; uvicorn, nginx or Docker host logs; pipecat modules nobody read.
- `BasicAuth`, `Bearer ` and the Telegram shape fire only if an exception repr or a logged header reaches the log. A normal call is expected to give 0 on old and new code alike (UNVERIFIED), so a Batch B zero there is weak evidence. T1/T1b carry that failure path.
- The first draft gated on `grep -cF 'auth = '`. It was dead: loguru never prints that label (see `2026-10-22-f09-loguru-diagnose-prints-failing-line-variables-only.md`), so it read 0 whether or not the fix worked. Replaced after review 2 (N1).
- Batch A exists to show the counters can fire on the old code at all.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.; `.agent/reports/review-2.md` N1.
