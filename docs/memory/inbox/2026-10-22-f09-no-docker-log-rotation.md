# F09: no log rotation in `docker-compose.yml`

- `docker-compose.yml` has no `logging:` key on any service, so Docker's default `json-file` driver keeps unbounded logs and they can fill the disk.
- UNVERIFIED: whether the VPS has a global limit in `/etc/docker/daemon.json`.
- Queued for later; not part of task 004.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.
