# F02: consent wording is versioned and held server-side

- The consent sentence for each version lives in `CONSENT_TEXTS` in `agent/demo_guard.py`; the server stores that text (never browser-supplied text) in `consents.consent_text`, with `consent_text_version`.
- v1 must never be edited in place: a request with no `consent_text_version` field is recorded as `v1`, so editing v1 would falsify old records. Changing even one character needs a new version in `CONSENT_TEXTS`, the page (`Hero.tsx`, `demoCall.ts`).
- An unknown version is refused with 400 `consent_version_unknown` before any dial.
- Source: live exit test 2026-10-14 at 870482a (founder report): `consents` row for a live-page call was `granted` / `web_form` / `v1` with the wording matching and `page_url` origin only; `v9` returned 400 `consent_version_unknown`. Code: `agent/demo_guard.py`.
