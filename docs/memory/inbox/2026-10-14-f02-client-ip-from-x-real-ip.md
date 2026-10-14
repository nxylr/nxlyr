# F02: /demo/call takes the client IP from X-Real-IP only

- `POST /demo/call` reads the client IP from nginx's `X-Real-IP` and never from `X-Forwarded-For` (nginx appends to a client-supplied `X-Forwarded-For`, so its leftmost entry is attacker-controlled).
- An absent or unparsable `X-Real-IP` is stored as NULL and counted in one shared Redis bucket named `unknown`. UNVERIFIED live: this fallback is covered by unit tests only.
- IPv6 callers are limited on their /64 network; the stored `consents.ip_address` is the unreduced address.
- Source: live exit test 2026-10-14 at 870482a (founder report): a request with forged `X-Forwarded-For` and `X-Real-IP` headers was stored with the caller's real IP. Code: `agent/demo_guard.py` `parse_client_ip`; spec `docs/issues/003-f02-demo-call-lockdown.md`.
