# Editing the VPS .env recreated the redis container — 2026-10-13

- Observed by the human on 2026-10-13: after editing `/mnt/secrets/.env` on the VPS and running `docker compose up -d --build`, the `redis` container showed "Created 2 seconds ago". It had been about 5 weeks old before.
- Not observed: any reset of the demo rate-limit counters or other Redis state. UNVERIFIED whether any state was lost.
- UNVERIFIED mechanism (inferred, not seen): both `agent` and `redis` use `env_file: /mnt/secrets/.env` in the repo copy of `docker-compose.yml`, so a changed env file would make Compose recreate both.
- The repo copy gives redis a named volume (`redis_data:/data`) and `--appendonly yes`, which should normally survive a recreate. To check what the VPS actually does, run on the VPS: `docker volume ls` and `docker compose config` (the VPS compose file may differ from the repo copy).
- Rule: a `.env` edit recreates redis, so don't edit `.env` while calls are in flight. This includes flipping `WS_AUTH_MODE`: a pending `ws_bind:*` binding (120s TTL) may not survive the recreate.
- Source: human observation, 2026-10-13; compose file read from the repo.
