# deploy.yml has no path filter: every docs merge rebuilds and recreates

- `.github/workflows/deploy.yml` triggers on every push to `main` with no path filter. A docs-only merge (PR #41, 1c711fd) rebuilt the agent image and recreated `nxlyr_agent` (new image id, created time 2026-10-24T11:41Z, uptime reset). A recreate wipes the in-container logs and latency files and makes the next call cold, so it is not comparable with the rest of a batch.
- Candidate fix: add `paths-ignore` for docs and markdown under `on.push`. A push where every changed file matches an ignored path skips the workflow; a PR that touches both docs and code still deploys, because one non-ignored file is enough.
- Caveats for whoever picks it up, so code changes never skip a deploy:
  - Use `paths-ignore` (a deny-list of known-harmless paths), not `paths` (an allow-list), so a new code location deploys by default.
  - Ignore only `docs/**` and `docs/memory/**`-style doc folders and root-level `*.md`. Do not ignore `**/*.md` blindly, `agent/**`, `Dockerfile`, `docker-compose.yml`, `requirements*`, `infra/**` or `.github/workflows/**`. Check that nothing under `agent/` or the build context reads a `.md` file at runtime before ignoring any `.md`.
  - Editing `deploy.yml` itself must still trigger a deploy of itself, so it must not be in the ignore list.
  - Check why a docs-only change altered the image (is `docs/` in the build context?). If it is, a `.dockerignore` entry may be a cleaner fix than, or an addition to, the path filter.
  - Add `workflow_dispatch` so a manual redeploy stays possible.
  - Vercel (frontend) deploys separately and is not affected by this change.
- Source: `.github/workflows/deploy.yml` read on 2026-10-24; container created times and image ids before and after the PR #41 deploy (founder session, 2026-10-24). The GitHub `paths-ignore` semantics are stated from general knowledge, not re-checked against current docs.
