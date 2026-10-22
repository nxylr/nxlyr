# F09: `/start` is unauthenticated and returns the raw Exotel body

- `/start` is unauthenticated in the code and returns the raw Exotel response body to the HTTP caller (`agent/server.py:246-253`). That is a response, not a log, so task 004 does not touch it.
- The repo copy of the nginx config has no `/start` location, so it falls to the static root and returns 404 (`infra/nginx/api.infrasmith.dev.conf`, locations at lines 118-157).
- UNVERIFIED: the live nginx file, other files in `sites-enabled/`, whether `/var/www/html/start` exists, what the Exotel tunnel exposes.
- Queued for the close-out docs PR.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.
