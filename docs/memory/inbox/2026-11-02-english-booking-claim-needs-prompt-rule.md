# English booking claim escaped the prompt rule — 2026-10-27

- Observed by the founder on a live call on 2026-10-27: the model said “Your site visit is set for Thursday…” before the booking tool returned.
- Task 021 extends `prompt_harness.py` so `claimed_without_tool` catches `set for`, `fixed for` and `scheduled for`; it does not change the English prompt.
- Follow-up: add the same invariant to the English prompt in a separate task with its own A/B test.
- Source: founder observation recorded in approved spec `docs/issues/021-multilingual.md`, decisions item 11 and risk R9.
- Update 2026-11-03: task 021 extended `prompt_harness.py` as described. The English prompt rule is parked in `hot.md` Next.
