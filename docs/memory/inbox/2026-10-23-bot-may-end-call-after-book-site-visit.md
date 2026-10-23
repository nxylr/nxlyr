# The bot may end the call after book_site_visit

- `book_site_visit` fired on 10 calls and `transfer_to_human` on 9 in both batches (baseline and exit). Asking for a site visit sometimes makes the bot wrap up and end the call. Needs checking before prompt v2 and task 008 are specced (hot.md Next 1).
- Source: events log, baseline 2026-10-22 and exit test 2026-10-23; founder notes in `docs/baselines/2026-10-23-011-exit.md`.
