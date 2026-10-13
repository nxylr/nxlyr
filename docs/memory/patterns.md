# Patterns that worked

- **One task, one issue, one worktree, one PR.** Keeps blast radius small and diffs reviewable.
- **Spec before code.** Acceptance criteria + exit test written first; builder gets only that.
- **Different model reviews.** Builder never reviews its own diff.
- **Tag steps** 🧑 YOU / 🤖 AGENT / 👀 VERIFY in every plan so human interference points are explicit.
- **Tested SQL before prod.** SQL is run on a local Postgres first, then the human runs it in Supabase SQL Editor with a backup `SELECT` first and a row-count check after.
- **Check twice** for container health, seconds apart.
- **Build gates for frontend:** `npm run build` plus grep for leftover `DRAFT`/placeholder text before committing.
