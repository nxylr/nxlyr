# Mistakes — do not repeat

| Date | What happened | Rule |
|---|---|---|
| 2026-10 | Plan assumed tables didn't exist; they did (leads, calls, transcripts…). | Inspect live schema (information_schema) before writing migrations. |
| 2026-10 | `grep … \|\| echo "none"` reported "none" because the log file didn't exist. | Check the file exists / read the exit code; grep exit 2 ≠ no match. |
| 2026-10 | Recursive CTE scan failed in Postgres (two recursive branches). | Use `jsonb_path_query` with `strict $.**` to scan jsonb. |
| 2026-10 | Supabase editor showed "RLS not enabled" mid-transaction. | False alarm; verify `relrowsecurity` after commit. |
| 2026-10 | Codex stopped on `npm ci` audit warnings. | Audit warnings are not blockers; continue, run `npm audit --omit=dev` read-only. |
| 2026-10 | Pitch deck contained fabricated stats and template residue. | Every number needs a source in `product.md`. |
| 2026-10 | zsh treats `#` in interactive commands as an argument. | Don't put inline comments in pasted shell commands. |
| 2026-10-13 | `new-task.sh` created task branches tracking `origin/main`, so a bare `git push` would target `main`. | `git worktree add --no-track`; always push with `git push -u origin task/<slug>`. |
| 2026-10-13 | `grep` with an unmatched shell glob (`--include=*.ts`) aborted the whole zsh command. | Quote globs or pass directories, not unexpanded patterns, in grep commands. |
