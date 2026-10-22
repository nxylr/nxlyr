# F09: the phone mask does not cover landline-style or toll-free numbers

- The new pattern in `agent/log_scrub.py` masks Indian mobiles (`[6-9]` then 9 digits, optional `+91`/`91`/`0`) and `+` followed by 10-15 digits. Not masked: `02212345678`, `18001234567`, digits glued to letters, spaced international forms.
- What Exotel sends in `from` and `to` has not been observed. If the ExoPhone (`to`) is landline-style it is logged in full: UNVERIFIED.
- Widening is a small follow-up with its own no-false-positive tests, once a real format escapes (Batch B's `masked=` count and last-6 gate are the signal).
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`. (review 1, R6).
