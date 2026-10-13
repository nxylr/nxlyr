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
