# AGENTS.md — NXLYR

Read this first. Every agent (Claude Code, Codex, Antigravity) reads this file. It is the single source of truth for how to work in this repo. `CLAUDE.md` just imports it.

## What NXLYR is

AI voice sales agent for Indian real-estate developers. A lead asks for a call → Exotel dials the lead → Exotel opens `wss://api.infrasmith.dev/ws` → Pipecat bot (Silero VAD with VAD and transcription turn-start strategies, Deepgram STT, GPT-4o, ElevenLabs TTS) talks to the lead. Tools (`book_site_visit`, `transfer_to_human`, `end_call`) write a Redis session hash. Knowledge base = `projects.config` (jsonb) in Supabase.

## Repo map (verify with `ls` before relying on it)

| Path | What |
|---|---|
| `agent/` | Python voice backend: `server.py` (routes /health /start /demo/call /contact /ws), `bot.py` (prompt + pipeline), `tools.py`, `kb_loader.py` |
| `dashboard/` | Next.js frontend (Vercel). Public site + demo form |
| `supabase/migrations/` | SQL record of schema. **Records only — never executed by agents** |
| `infra/nginx/` | nginx config copy for api.infrasmith.dev |
| `.github/workflows/` | CI + `deploy.yml` |
| `docs/memory/` | Project memory (see below) |
| `docs/adr/` | Architecture decision records |
| `docs/issues/` | Task specs written before work starts |

## The 9 non-negotiable rules (full text in CONSTRAINTS.md)

1. Every code change happens in a fresh git worktree, never on `main`. Show the diff before committing.
2. On the VPS, `git pull` and `docker compose up -d --build` are an inseparable pair.
3. Any nginx change: back up outside `sites-enabled/`, `nginx -t` before reload, stop on failure, `curl` afterwards.
4. Container health: check twice, a few seconds apart.
5. Real secrets are never pasted into or handled by an agent. The human edits them directly on the VPS.
6. A diff looking correct is not proof. The gate is a real test: real call, real DB row, real notification.
7. Never fabricate social proof, statistics, or claims.
8. Schema changes: agent writes SQL, human reviews and runs it in Supabase SQL Editor.
9. Surprising or ambiguous finding → stop and report plainly. Do not guess or work around silently.

## Hard stops for agents

- **Merge = deploy.** Pushing to `main` triggers `deploy.yml` (SSH → `git pull` → `docker compose up -d --build`) and Vercel production. **Agents never merge, never push to `main`.** The human merges.
- Never read, print, or `cat` `.env*` files (except `.env.template`/`.env.example`), key files, or Telegram/API tokens. If a task needs a secret, stop and say which variable name is needed.
- Never run `SELECT *` on `tenants` (contains `api_key`).
- Logs may contain secrets (prompts, Redis URL). Do not paste logs into PRs, issues, or memory files unredacted.
- Never run SQL against production. Never SSH to the VPS unless the issue explicitly says so and the human is present.
- Do not touch files outside the issue's "Files in scope" list without asking.

## Workflow (one task = one issue = one worktree = one PR)

1. **Spec** — a file in `docs/issues/NNN-slug.md` (template: `.github/ISSUE_TEMPLATE/task.md`). Written by Claude (lead) and approved by the human **before** code.
2. **Worktree** — `scripts/new-task.sh NNN-slug` (creates `../nxlyr-worktrees/NNN-slug` on branch `task/NNN-slug` from fresh `origin/main`).
3. **Build** — builder agent (default Codex) implements only what the spec says. Small commits.
4. **Tag every step** in reports: 🧑 YOU / 🤖 AGENT / 👀 VERIFY, so the human knows where they are needed.
5. **Review** — a *different* model from the builder reviews the diff (`/codex:review` or `/codex:adversarial-review` from Claude Code; or Claude reviews Codex output). **The agent that wrote the code never reviews it.**
6. **PR** — body must contain the 10 headings in `.github/pull_request_template.md`. CI (`pr-report.yml`) fails if any is missing or empty.
7. **Real test** — the human runs the exit test from the issue (real call / real row / real notification) and pastes the evidence into PR section "Evidence".
8. **Human merges.** Then `scripts/finish-task.sh NNN-slug` removes the worktree.
9. **Memory** — before closing, update `docs/memory/` (see below).

## Roles

| Agent | Role | Does | Does not |
|---|---|---|---|
| Claude Code | Lead | Specs, plans, architecture, final PR report, cross-review of Codex diffs | Bulk implementation (quota) |
| Codex | Builder | Implements specs in worktrees, writes tests | Review its own diff; change scope |
| Antigravity | QA / UI / docs | Frontend work, browser checks, screenshots, docs | Backend/voice pipeline changes |

Keep at most **3 worktrees** open at once. Claude Pro quota is the tightest: use it for short, high-leverage tasks (spec, plan, review).

## Memory (the repo is the memory)

Agents have no memory between sessions. Read these at session start, in order:

1. `docs/memory/hot.md` — current state, what's in flight, next 3 things. **Read every session. Keep < 60 lines.**
2. `docs/memory/architecture.md` — how the system actually works (verified facts only).
3. `docs/memory/decisions.md` — index of ADRs in `docs/adr/`.
4. `docs/memory/mistakes.md` — things that went wrong; do not repeat.
5. `docs/memory/patterns.md` — conventions that worked.
6. `docs/memory/product.md` — what is built vs. planned (source of truth for any claim made publicly).
7. `docs/memory/log.md` — append-only dated log. Read only the tail.

**Writing memory:** agents drop notes in `docs/memory/inbox/YYYY-MM-DD-slug.md` (one fact per file, with source). The human or Claude (lead) promotes inbox notes into the files above. Agents do not rewrite `hot.md`/`decisions.md` directly except when the issue says so. Never record unverified claims as facts: mark `UNVERIFIED:`.

## Definition of done

- Spec's acceptance criteria all met, each with evidence in the PR.
- Tests added/updated; local test command output pasted.
- The issue's **exit test** has been run by the human on the real system (or explicitly marked "Not verified" in the PR with the reason).
- Review by a different model recorded in PR.
- Memory inbox note added if anything was learned.

## Commands (verify they work; fix this section if not)

```bash
# The Python venv (agent/venv, Python 3.12) exists ONLY in the main checkout: it is gitignored,
# so worktrees have none. From a worktree, point at the main checkout's interpreter.
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PY="$MAIN/agent/venv/bin/python"
# backend unit tests (from the repository/worktree root)
"$PY" -m unittest agent.test_ws_auth      # F01 admission tests; mocked Redis, no live service
"$PY" -m unittest agent.test_kb_loader    # passes since task 015 (F23 fixed); no network
"$PY" -m unittest agent.test_startup_timing  # call timing log lines, KB preload and refresh, timeouts (task 015); no network
"$PY" -m unittest agent.test_prompt       # prompt text, greeting, tool strings (task 014); no network
# backend import smoke (from agent/ of the worktree)
(cd agent && "$PY" -c "import server, week2_latency_observer")  # matches Dockerfile
# No backend Ruff command yet: Ruff has no repository config or declared dependency.
# The current CI target (ruff check api/) is stale because api/ does not exist.
# frontend (from dashboard/)
npm ci && npm run build                  # build gate
npm run lint
# tasks
scripts/new-task.sh 001-f01-authenticate-ws
scripts/finish-task.sh 001-f01-authenticate-ws
```

## Style

- Python: small functions, type hints on new code, no bare `except:`; never swallow errors that change a success/failure report (see audit F04).
- Timeouts on every network call (audit F12). No blocking calls in the async pipeline (F06).
- No new dependency without a line in the PR explaining why.
- Public-facing copy states only what exists today (`docs/memory/product.md`).
- Prefer the smallest change that meets the acceptance criteria. Note shortcuts under "Shortcuts and debt" in the PR.
