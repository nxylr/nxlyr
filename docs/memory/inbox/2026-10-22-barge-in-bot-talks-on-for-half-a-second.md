# After a barge-in the bot keeps talking for 0.5 to 1 s

- When the caller starts to cut in, the bot's sentence runs on for 0.5 to 1 s before it stops. The cut-off itself works.
- Source: founder notes, baseline 2026-10-22 (`docs/baselines/2026-10-22-baseline.md`).
- Update 2026-11-03 (task 022, per the founder, not verified by an agent): in smart mode `clear` was sent within 6 to 9 ms of the decision to interrupt. Whether the audible 0.5 s tail is gone was not reported; still open.
