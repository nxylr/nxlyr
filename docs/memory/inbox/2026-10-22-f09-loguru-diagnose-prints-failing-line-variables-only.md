# F09: loguru `diagnose=True` annotates only the failing line's variables, as bare values

- It annotates only the variables that appear on the failing source line of each traceback frame, not every local. Verified with a toy example on loguru 0.7.3.
- The annotation is the value's repr under `│`/`└` marks. There is no `name = value` text, so a grep for `auth = ` can never match it.
- So the earlier claims that tracebacks leak "every local", the Telegram bot token or the prompt via `run_bot` frames were overstated and are unproven. The audit's phone number at `server.py:570` is not supported by reading (the failing line names `request` and `call_sid`). The Exotel call site (`auth`, `data` on the failing line) is consistent with the audit but not reproduced.
- `diagnose=False` removes the whole class either way, so the fix does not depend on which of these were real.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.; `.agent/reports/review-2.md` N1; toy example re-run 2026-10-22.
