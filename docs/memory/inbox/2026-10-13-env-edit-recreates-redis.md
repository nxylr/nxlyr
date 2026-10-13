# Editing the VPS .env recreated the redis container — 2026-10-13

- Observed by the human on 2026-10-13: after editing `/mnt/secrets/.env` on the VPS and running `docker compose up -d --build`, the `redis` container showed "Created 2 seconds ago". It had been about 5 weeks old before.
- Follow-up check by the human on the VPS, 2026-10-13: `docker volume ls` shows `nxlyr_redis_data`, and `redis-cli DBSIZE` returned 7 right after the recreate. Consistent with the data surviving the recreate (named volume + `--appendonly yes` in the repo copy of `docker-compose.yml`), though not proof: the key count before the recreate was not recorded.
- Status: **likely survives; not proven.** Counter resets were never observed.
- Mechanism (inferred, not seen): both `agent` and `redis` use `env_file: /mnt/secrets/.env`, so a changed env file makes Compose recreate both.
- To prove it next time: run `redis-cli DBSIZE` (and note a known key, e.g. `demo:rate:global:<date>`) before the `.env` edit and again after the `up -d`. `docker compose config` on the VPS shows whether the live compose file matches the repo copy.
- Rule: a `.env` edit recreates redis, so don't edit `.env` while calls are in flight. This includes flipping `WS_AUTH_MODE`: a pending `ws_bind:*` binding (120s TTL) may be lost if the container is restarted during a call setup.
- Source: human observation and VPS check, 2026-10-13; compose file read from the repo.
