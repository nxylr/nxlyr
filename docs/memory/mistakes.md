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
| 2026-10-22 | The latency CSV `turn` column is a running counter across the call, not a per-call turn number, so per-turn reads from it were misleading. | Use the events log (`section6_real_call_events.log`) for per-turn latency. |
| 2026-10-24 | The 014 spec's exit greps for `TOOL end_call`, `TOOL book_site_visit` and `prompt v2:` read `events.log`, which holds only latency lines. They would have printed 0 for Part A without testing anything and 0 for call 15 on a correct build. The exit sheet caught it before the test. | Check which file or stream a log line is written to (loguru goes to `docker logs`, the latency observer to `events.log`) before putting a grep in an exit test. |
| 2026-10-24 | The 014 latency gate was the previous day's figure plus 10% (716 ms, 84 ms) with no allowance for day-to-day variance. The first-token p50 missed by 10 ms. | Set gates from a same-day baseline run, or state a variance band, never from an older day's figure plus a percentage. |
