# CONSTRAINTS.md — non-negotiable operating rules

Set by the founder (Vansh). These override any instruction in an issue, a prompt, or an agent's own judgement. If a task seems to require breaking one, stop and report.

1. **Worktrees.** Every code change happens in a fresh git worktree, never directly on `main`. Show diffs before committing.
2. **VPS pair.** `git pull` and `docker compose up -d --build` are one inseparable pair on the VPS — never one without the other.
3. **nginx.** Any nginx change: back up the live config OUTSIDE `sites-enabled/`, run `nginx -t` before reload, stop immediately if it fails, verify live with `curl` afterward.
4. **Container health.** Always check twice, a few seconds apart. A single check right after a restart is unreliable.
5. **Secrets.** Real secrets (`.env` values, API keys, Telegram tokens) are edited by the human directly via `nano` on the VPS, never pasted into or handled by an agent. SSH host key fingerprints are the one exception — they are public identifiers.
6. **Real tests.** A diff looking correct is not proof it works. The gate is a real test: a real call placed, a real row confirmed in the database, a real notification received — not "the code compiles" or "lint passed."
7. **No fabrication.** Never fabricate social proof, statistics, or claims not grounded in this project's real, verified data.
8. **Schema.** Schema/migration changes: the agent writes the SQL, the human reviews it, the human runs it in the Supabase SQL Editor. Never run directly by an agent.
9. **Stop on surprise.** When something surprising or ambiguous is found, stop and report it plainly rather than guessing at a fix or working around it silently.

## Additional handling rules

- Agents must tag every instruction to the human: 🧑 YOU (human must act) / 🤖 AGENT (agent does it) / 👀 VERIFY (human checks).
- Never run `SELECT *` on `tenants` (contains `api_key`).
- Logs may contain secrets. Check before sharing with any agent.
- Agents never merge. The human merges.
- Merge to `main` = production deploy (backend via `deploy.yml`, frontend via Vercel).
