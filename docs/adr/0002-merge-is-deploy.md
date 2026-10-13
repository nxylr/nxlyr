# ADR 0002: Merge is deploy (for now)

- Status: Accepted (revisit when a staging environment exists)
- Date: 2026-10-13

## Context
`deploy.yml` deploys on every push to `main` (SSH → `git pull` → `docker compose up -d --build`); Vercel production follows `main`. No concurrency control, no staging.

## Decision
- Treat every merge to `main` as a production deploy. Merge only when the exit test has been run and the human is available to check container health twice afterwards.
- Agents never merge or push to `main`.
- Merging the agent-kit PR itself triggers `deploy.yml` although `agent/` is unchanged; this is accepted (rebuild is a no-op in behaviour) — the human watches the deploy run.
- New-feature testing happens on `task/*` branches, locally (docker compose + mock Exotel + prompt harness) and in PR CI. A real staging environment is a separate decision.

## Consequences
- Slower merges, safer demo.
- Future work: path filters or manual approval on `deploy.yml`, concurrency group, staging.
