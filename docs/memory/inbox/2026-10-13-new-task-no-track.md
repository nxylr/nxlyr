# new-task.sh should use --no-track — 2026-10-13

- `scripts/new-task.sh` runs `git worktree add -b task/<slug> <dir> origin/main`, which sets the new branch to track `origin/main`. Use `--no-track` so a bare `git push` can never target `main`.
- Source: observed when creating worktree 001-f01-authenticate-ws ("branch 'task/001-f01-authenticate-ws' set up to track 'origin/main'").
