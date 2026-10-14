# F02: /demo/call kill switch and caps are changed in Redis, not by deploy

- Redis key `demo:kill` set to any non-empty value makes `/demo/call` return 503 `demo_disabled` before anything else (checked before phone validation). `DEL demo:kill` re-enables. An empty-string value does not disable (by code and review; not tested live).
- Redis hash `demo:config` overrides the defaults at runtime, read per request: `phone_limit` 3, `ip_limit` 10, `global_limit` 50, `phone_cooldown_seconds` 180, `ip_cooldown_seconds` 30, `window_seconds` 86400. A missing, non-integer or `< 1` value falls back to the default.
- Commands (run inside the redis container, DB 0, no password): see "Operator commands" in `docs/issues/003-f02-demo-call-lockdown.md`. Editing the VPS `.env` is not needed and must be avoided (it recreates redis).
- Source: live exit test 2026-10-14 at 870482a (founder report): kill switch returned 503 then normal after `DEL`; `limit=ip` and `limit=global` 429s were produced through `demo:config`. Config fallback for invalid values: UNVERIFIED live (unit tests only).
