# Log (append-only, newest at bottom)

- 2026-09-05 contact_submissions migration added.
- 2026-10-07 Phase 0: `commitments` + `consents` tables applied in production via Supabase SQL Editor.
- 2026-10-0x Independent audit (F01–F26) received; fixes drafted as PRs #29 (F04/F05), #30 (CI), #31 (site copy F10). Not merged by founder decision; live demo stays on 80d4348.
- 2026-10-13 Agent workflow kit created (AGENTS.md, memory, PR report, worktree scripts). Next: F01.
- 2026-10-13 Founder correction: the live site on `main` still contains the F10 overclaims (“Sending transcript”, “Updated CRM”, inbound-routing and DPDP claims); F04, F05, F10 and F11 are open. PRs #29–#31 are closed unmerged; their branches and diffs remain on GitHub, and the work can be reopened.
- 2026-10-13 F01 evidence call: Exotel Call SID == `/ws` `call_sid` (one real call); dial to answer ~12s; source IP not captured.
- 2026-10-13 PR #33 merged (7cf8edf): `/ws` one-shot binding auth, `WS_AUTH_MODE` code default `log`. Founder reports `WS_AUTH_MODE=enforce` set on the VPS (not verified by an agent).
- 2026-10-13 F01 exit-test evidence (human, VPS, `WS_AUTH_MODE=enforce`): real call logged `ws_auth bound ok` at 17:20:06 UTC; an anonymous probe and a replayed used SID were both closed with 1008 and logged `rejected reason=no_binding`; no "admitted" or "Exotel call connected" lines for the probe SIDs.
- 2026-10-13 Task 002 memory close-out: inbox notes promoted, AGENTS.md Commands corrected (venv only in main checkout; 5 `test_kb_loader` failures on `main`, F23), `new-task.sh` uses `--no-track`.
