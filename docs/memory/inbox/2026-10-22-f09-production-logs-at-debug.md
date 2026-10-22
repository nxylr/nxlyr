# F09: production logs at DEBUG

- `LOG_LEVEL` is not in the VPS `.env` (founder, 2026-10-22; the container check showed it empty). The code default in `agent/bot.py:96` is `DEBUG`, so production runs `DEBUG`.
- A *set-but-empty* `LOG_LEVEL` would crash boot (checked locally: loguru raises `ValueError: Level '' does not exist`), so the variable is unset, not empty.
- Status: founder-reported; no agent has read the VPS.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.
