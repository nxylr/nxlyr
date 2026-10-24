# "Meridian Heights" was misheard and repeated as "Eridian Heights"

- STT heard the project name wrongly and the bot said "Eridian Heights". Candidate fix: project names as Deepgram key terms, plus a prompt rule to confirm a name it is unsure of (STT A/B).
- Source: founder notes, `docs/baselines/2026-10-23-011-exit.md`.
- Update 2026-10-24: prompt v2 (014) added the prompt half, "if the caller says a name close to the project name, ask "Did you mean ...?" first". The STT half (Deepgram key terms) is still open. Whether the rule worked was not scored in the 014 exit test.
