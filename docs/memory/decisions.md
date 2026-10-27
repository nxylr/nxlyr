# Decisions index

Full records in `docs/adr/`. One line each; newest last.

| ADR | Decision | Status |
|---|---|---|
| 0001 | Multi-agent workflow: worktree per task, builder ≠ reviewer, repo is the memory | Accepted 2026-10-13 |
| 0002 | Merge-is-deploy accepted for now; agents never merge; revisit with staging | Accepted 2026-10-13 |

## Standing decisions without an ADR yet
- 2026-10: Keep PRs #29/#30/#31 unmerged to preserve the live demo; founder reads code/schema first.
- 2026-10: F01 (unauthenticated `/ws`) is the first real task under the new workflow. Done 2026-10-13 (PR #33, 7cf8edf).
- 2026-10-13: `/ws` is authenticated by a one-shot Redis binding keyed by the Exotel Call SID (`WS_AUTH_MODE` log→enforce, code default `log`). A handshake token via `CustomField` is an open question, not implemented (spec 001).
- 2026-10-13: Ponytail plugin pinned at 5.2.0 (`https://github.com/DietrichGebert/ponytail.git`, commit `2961b52fc1fe6a5a87c7a959a79512e5c2f3ffe5`). Its hooks auto-activate in Claude Code and are left active on purpose. Do not update it without re-reviewing the hooks.
- 2026-10: Skip OmniRoute (conflicts with provider terms for plan logins). Do not enable the Codex Stop-hook review gate.
- 2026-10-23: Prompt v2 AI disclosure: the bot says it is an AI only when asked, and then at once and truthfully, never denying it. **Pending the lawyer's answer on TRAI and DPDP**; if the answer requires disclosure up front, this decision changes.
- 2026-10-23: The agent is named Aarya, with a female voice.
- 2026-10-23: The caller's name comes from a demo-form field now and from lead ingestion later. The form of address (sir, ma'am or name only) is chosen by the visitor or taken from the lead record, never guessed from the name. With no name, the bot never uses one.
- 2026-10-24: AI disclosure is `on_ask` for the demo (`AI_DISCLOSURE_MODE` in `agent/prompt.py`): the bot says it is an AI only when asked, then at once and truthfully. `upfront` is reserved for a pilot, and the lawyer's answer on TRAI and DPDP is still pending.
- 2026-10-24: The spoken company name is "Next Layer" (`COMPANY_SPOKEN`); "NXLYR" appears only in logs, UI and docs (`COMPANY_DISPLAY`). The prompt and every spoken string use the spoken form.
- 2026-10-24: The payment plan is said as one plain sentence, not a ratio, using a `spoken` key in the knowledge base (`payment_plan.spoken`).
- 2026-10-24: The model-preload follow-up (spec 015, Part 3) is closed. The VPS figure after 015 is `models_ms` 111 / 102 / 98 ms against the 150 ms threshold, so the VAD and Smart Turn analyzers stay built per call, off the event loop. Reopen it only if `models_ms` goes over 150 ms.
- 2026-10-25: Prompt v2.1 goes live through Redis (`convo:config` prompt_version=v21), not by changing the code default, which stays v2. Same for key terms and the EU Deepgram endpoint: on in Redis, off in code. Rollback is `DEL convo:config`, no deploy. (Spec 018; the live values are per the founder, not verified by an agent.)
- 2026-10-26: Voice settings are tuned per call through `voice:config` (Redis > environment > code default per field); with no override the ElevenLabs request is unchanged. On `eleven_v4*` only stability and similarity_boost are sent (spec 019; see the open v4 finding in the inbox).
- 2026-10-27: Alert before booked (spec 008): the bot may say a visit is booked or a callback passed on only after a `call_commitments` row is stored and a Telegram alert is delivered. Otherwise code speaks a fixed "not confirmed" sentence. `transfer_to_human` is an honest callback request, not a live transfer.
- 2026-10-27: A correction on the same call supersedes the earlier booking row (kept, `superseded_at` set) and sends an "Updated booking" alert; one live row per call.
- 2026-10-27: **Founder decision: the beachhead is Gurugram residential developers.** Next work follows the Gurugram plan in `hot.md`.
- 2026-10-27: Numerals are not forced on Deepgram (`stt_numerals` stays off): its formatting already gives digits (per the founder, 018 exit test).
