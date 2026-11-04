# Patterns that worked

- **One task, one issue, one worktree, one PR.** Keeps blast radius small and diffs reviewable.
- **Spec before code.** Acceptance criteria + exit test written first; builder gets only that.
- **Different model reviews.** Builder never reviews its own diff.
- **Tag steps** 🧑 YOU / 🤖 AGENT / 👀 VERIFY in every plan so human interference points are explicit.
- **Tested SQL before prod.** SQL is run on a local Postgres first, then the human runs it in Supabase SQL Editor with a backup `SELECT` first and a row-count check after.
- **Check twice** for container health, seconds apart.
- **Build gates for frontend:** `npm run build` plus grep for leftover `DRAFT`/placeholder text before committing.
- **Ship gates in log mode first.** A new auth/limit check ships with `log` as the code default (never rejects, logs `would_reject`), is proven with a real call, then flipped to `enforce` by the human in the VPS `.env`. (F01: `WS_AUTH_MODE`.)
- **Local end-to-end before the VPS:** Redis in Docker on a spare port + `agent/mock_exotel_client.py` + dummy API keys, server run from the worktree. Proves admit/refuse paths without paid calls.
- **Review the replay path, not just the gate.** When a handler consumes frames to decide, check every failure path puts them back (binary frame, early disconnect, timeout).
- **PRs that touch the same file merge one at a time.** The second takes `origin/main`, resolves, and reruns every test module before it merges (004 and 011 both edited the import block in `bot.py`; all five modules passed after the merge).
- **Set T0 once, right before the calls.** Every count (leaks, stalls, latency) is "since T0"; a T0 set earlier pulls in other calls. Use the events log for latency, not the CSV.
- **Switch in Redis, default in code.** A new behaviour ships with the old one as the code default and a per-call Redis switch (`convo:config`, `voice:config`). The founder turns it on between calls, compares blocks of real calls, and reverts with `DEL`, no deploy. Invalid values and Redis trouble must fall back with a WARNING, never break a call. (018, 019, 022 `bargein_mode`, 021 `language_mode`.)
- **Alert before booked.** A tool that makes a promise stores the row, delivers the alert, and only then reports success; every failure path speaks a fixed sentence from code (`run_llm=False`). Keep the post-alert steps in one retained task so a hang-up cannot cancel them. (008.)
- **Exit tests in back-to-back blocks.** One uncounted warm-up call, then one block per setting with a snapshot after each, and a cut rule agreed before the run (spec 018 r3).
- **Measure the control the same way.** A new behaviour behind a switch logs the same line in both modes (022: `barge-in:` with `mode=legacy|smart`), so the comparison is like for like. A degrade-on-failure chain logs one line per step (021: `stt fallback: step=…`), so a real call can show whether it ever fired.
- **Settle a vendor-behaviour question with a test that names it.** The Pipecat interrupt-commits-text fact is pinned by `test_a8_interruption_commits_assistant_text_already_pushed`; if Pipecat changes, that test fails instead of a memory note going quietly stale.
