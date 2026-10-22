# F09: two of our own log lines leaked

- `agent/tools.py:507` (INFO, every call) logged `Redis connected ({redis_url})`: the `redis://` line seen in the logs. A Redis URL can carry a password.
- `agent/server.py:243-245` logged the raw Exotel response body on a non-200 (dialled number, caller id, account sid).
- Both by reading the source, not run. Fixed in task 004 (URL and body removed at the source).
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.
