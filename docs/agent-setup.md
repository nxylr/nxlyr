# NXLYR agent kit — setup (about 45–60 min, once)

Tags: 🧑 YOU = only you can do it · 🤖 AGENT = an agent may do it · 👀 VERIFY = you check the result.

## What is in this kit

| File | Purpose |
|---|---|
| `AGENTS.md` | Rules, roles, workflow, memory protocol. All three agents read it |
| `CLAUDE.md` | Imports AGENTS.md + CONSTRAINTS.md for Claude Code |
| `CONSTRAINTS.md` | Your 9 non-negotiable rules, verbatim |
| `.claude/settings.json` | Shared permission rules (deny `.env`, force-push, merge, ssh, psql…) |
| `.github/pull_request_template.md` + `workflows/pr-report.yml` + `scripts/check-pr-report.py` | 10-heading PR report, enforced in CI |
| `.github/ISSUE_TEMPLATE/task.md` | Spec template |
| `scripts/new-task.sh`, `finish-task.sh`, `setup-labels.sh` | Worktree per task (max 3 open), cleanup, labels |
| `docs/memory/*` | hot, architecture, product, decisions, patterns, mistakes, log, inbox/ |
| `docs/adr/0000-0002` | ADR template + workflow + merge-is-deploy |
| `docs/issues/001-f01-authenticate-ws.md` | First real task: fix the unauthenticated demo |
| `gitignore.additions` | Lines to append to `.gitignore` |

Tested here: scripts (syntax, create, duplicate, bad name, 3-worktree cap, finish merged/unmerged), PR-report check (empty template fails, complete passes, missing heading fails), `settings.json` is valid JSON. Not tested: anything against your real repo, GitHub, or the plugins.

## Step 0 — Tools you need 🧑

| Tool | Check | Why |
|---|---|---|
| git ≥ 2.30 | `git --version` | worktrees |
| gh (GitHub CLI) | `gh auth status` | labels, PRs |
| Node ≥ 18.18 | `node -v` | codex-plugin-cc, dashboard |
| Python 3.11+ | `python3 --version` | tests, PR check |
| Claude Code | `claude --version` | lead |
| Codex CLI ≥ 0.122 | `codex --version` | builder, plugin support |
| Antigravity | `agy --version` | QA/UI/docs |
| Docker Desktop | `docker --version` | local sandbox |

## Step 1 — Seed the repo through a worktree (the kit follows its own rule) 🧑

Unzip the kit somewhere outside the repo, e.g. `~/Downloads/nxlyr-agent-kit`. Then, from your local clone:

```
cd "/Users/vansh/Desktop/SALES AGENT/<your-repo-folder>"
git fetch origin main
git worktree add -b setup/agent-kit "../nxlyr-worktrees/agent-kit" origin/main
cd "../nxlyr-worktrees/agent-kit"
cp -R ~/Downloads/nxlyr-agent-kit/. .
mv SETUP.md docs/agent-setup.md
cat gitignore.additions >> .gitignore && rm gitignore.additions
chmod +x scripts/*.sh scripts/*.py
git add -A
git status
```

👀 VERIFY: `git status` must list only new files plus `.gitignore`. If it shows any change under `agent/` or `dashboard/`, stop and tell me.
👀 VERIFY: `git ls-files | grep -E "\.env"` prints nothing except possibly `.env.template`/`.env.example`.

If the repo already has an `AGENTS.md`, `CLAUDE.md` or `.claude/settings.json`, do not overwrite: stop and show me the diff.

Then:

```
git commit -m "chore: add agent workflow kit (AGENTS.md, memory, PR report, worktree scripts)"
git push -u origin setup/agent-kit
gh pr create --fill
```

Open the PR and fill the 10 headings yourself (Tools used: none; Not verified: workflows untested on GitHub until this PR runs). 👀 The `PR report` check should appear on this very PR and go green. **Merging this PR triggers `deploy.yml`** even though `agent/` is unchanged. It rebuilds the same code. Watch the Actions run, then check container health twice a few seconds apart. If you prefer zero deploy risk, merge it later when you next deploy anyway.

After merge: `git worktree remove ../nxlyr-worktrees/agent-kit`, then pull `main`.

## Step 2 — Labels (optional, 1 min) 🧑
`bash scripts/setup-labels.sh`

## Step 3 — Plugins, in this order 🧑

Run inside Claude Code unless stated. All commands below were taken from each project's README.

1. **agent-skills**
   - Claude: `/plugin marketplace add addyosmani/agent-skills` then `/plugin install agent-skills@addy-agent-skills`
   - Codex: `codex plugin marketplace add addyosmani/agent-skills` then `codex plugin add agent-skills@agent-skills`
   - Antigravity: `agy plugin install https://github.com/addyosmani/agent-skills.git` (call skills by name; command wrappers may not show)
2. **ponytail** (install only from `DietrichGebert/ponytail`)
   - Claude: `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail`
   - Codex: `codex plugin marketplace add DietrichGebert/ponytail`, `codex plugin add ponytail@ponytail`, then trust its hooks in `/hooks`
3. **codex-plugin-cc** (lets Claude Code call Codex for review)
   - `/plugin marketplace add openai/codex-plugin-cc`, `/plugin install codex@openai-codex`, `/reload-plugins`, `/codex:setup`
   - Use `/codex:review` and `/codex:adversarial-review`. **Do not enable the Stop-hook review gate.**
4. **pstack, graphify** — I did not verify their install commands. Skip until the core loop has run for one full task. If you want them later, ask me and I will check the READMEs first.
5. **OmniRoute** — skip.

👀 After each install run `/plugin` and confirm it lists as enabled. Run `claude doctor`; it must not report rejected settings entries.

## Step 4 — How memory forms

There is no command that creates memory. It forms because:
1. Step 1 puts `AGENTS.md` and `docs/memory/*` in the repo, so every agent reads them at session start (Claude via `CLAUDE.md` imports; Codex and Antigravity read `AGENTS.md`).
2. During a task, agents drop one-fact notes in `docs/memory/inbox/`.
3. At the end of a task, Claude promotes inbox notes into `hot.md`, `mistakes.md`, `architecture.md`, etc., and you review that diff like any other.

👀 Check at the start of your first session: ask the agent "what are the next 3 things?" It must answer from `docs/memory/hot.md` (F01, sandbox, transcripts). If it can't, the file isn't being read.

`docs/memory/*` has been pre-filled with facts from our sessions. Skim `architecture.md` and `product.md` and correct anything wrong; they become the source of truth.

## Step 5 — GitHub protection 🧑
Settings → Branches → rule for `main`: require PR, require the `PR report` check (and CI once PR #30 lands). If your plan blocks this on a private repo, the rule "agents never merge" in `CONSTRAINTS.md` is the only guard, so keep the deny rules in `.claude/settings.json`.

## Step 6 — Pilot: Task 001, fix unauthenticated demo access

Spec is `docs/issues/001-f01-authenticate-ws.md`. Order:
1. 🧑 Place one real demo call on the live system and collect the Call SID vs `/ws` `call_sid` evidence (spec step 1). Check logs for secrets before sharing.
2. 🤖 Claude confirms the design from the evidence. 🧑 You approve.
3. `scripts/new-task.sh 001-f01-authenticate-ws` → 🤖 Codex builds → 👀 you read the diff → 🤖 Claude reviews → PR → 🧑 exit test → 🧑 you merge.

## Quota habits
- Claude Pro: spec, plan, review, PR report only. Codex does bulk coding. Antigravity does UI and browser checks.
- Max 3 worktrees. Close a task fully (memory, `finish-task.sh`) before opening another.
- Start a fresh session per task; the repo is the memory.

## Known limits of this kit
- The exec bit may be lost when unzipping; the `chmod +x` line in Step 1 fixes it.
- `AGENTS.md` "Commands" section is my best reading of the repo layout; I haven't opened the repo. Verify each command once and correct the file in the setup PR.
- `docker compose` is set to "ask" (not deny) so local sandbox runs work. `ssh`, `scp` and `psql` are denied: VPS and database work stays with you.
