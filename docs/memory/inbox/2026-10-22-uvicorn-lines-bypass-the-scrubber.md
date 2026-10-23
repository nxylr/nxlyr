# uvicorn's own log lines bypass the scrubber

- `agent/log_scrub.py` installs one loguru handler. uvicorn writes through the standard `logging` module, so its lines are not scrubbed or masked.
- Source: task 004 (PR #38) design; founder statement at close-out 2026-10-23. UNVERIFIED: whether any uvicorn line currently carries a phone number.
