# 011 — F07 turn release

**Status: APPROVED r2 (founder)**

## Goal

Remove the up-to-three-second F07 turn-release stall after a caller finishes speaking, while retaining Smart Turn v3 as the normal semantic end-of-turn signal and not cutting off a caller during a short mid-sentence pause. The default mode is `NXLYR_TURN_MODE=smart_backstop`: Smart Turn v3 remains first in the stop-strategy list and `SpeechTimeoutUserTurnStopStrategy` is its independent backstop. The backstop is `0.8` seconds after the existing VAD stop event, which is approximately `1.0` seconds after actual silence begins because the unchanged VAD stop window is `0.2` seconds; test tolerance permits no more than `1.2` seconds from actual silence.

`NXLYR_TURN_MODE=speech_timeout` selects timer-only comparison mode with one `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)`. An unset flag means `smart_backstop`.

Context: F07 and `docs/research/latency-audit.md` sections 2 and 8. The audit was written at `188624e`; this worktree is based on `main` at `1e47490`.

## Non-goals

- Do not change Silero VAD parameters or turn-start strategies.
- Do not change Deepgram settings, the LLM, TTS, prompt, transport, provider credentials, or database behavior.
- Do not execute SQL or add a migration.
- Do not change the latency observer's CSV schema or alter `latency_report.py`.
- Do not add a real-call driver, deploy, commit, push, or merge as part of this task.

## Design (files to touch and why)

| File | Change | Why |
| --- | --- | --- |
| `agent/bot.py` | Add immutable process-start configuration for `NXLYR_TURN_MODE` and `NXLYR_TURN_BACKSTOP_SECS`; validate it during module/process startup, before any call is admitted; use it in a small, directly unit-testable turn-strategy factory that passes an explicit `stop=[...]` list to the existing `UserTurnStrategies`. | The current `UserTurnStrategies(start=[...])` at lines 490–495 silently takes Pipecat's three-second Smart Turn default. Startup validation turns a typo into a failed container health check instead of a per-call failure or a silent fallback. |
| `agent/test_turn_release.py` (new) | Async unit tests using Pipecat's controller, deterministic fake analyzer, and injected fake timer/clock; no provider, audio device, database, or network. | Proves the fallback race and pause behavior without loading the ONNX model or making a billable call or relying on wall-clock scheduling. |
| `.env.template` | Document `NXLYR_TURN_MODE=smart_backstop`, `NXLYR_TURN_BACKSTOP_SECS=0.8`, their allowed values/ranges, and that neither is a secret. | Makes the default, field-test switch, and tunable backstop discoverable to the human who edits the VPS environment. |
| `docs/issues/011-f07-turn-release.md` | This approved scope and test contract. | Keeps implementation bounded to F07. |

Implementation contract:

Exact Pipecat 1.5.0 imports (proven against the main-checkout venv; do not import either stop strategy from `pipecat.turns.user_turn_strategies`):

```python
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_stop import (
    SpeechTimeoutUserTurnStopStrategy,
    TurnAnalyzerUserTurnStopStrategy,
)
```

1. At process startup, parse and validate configuration exactly once, before `run_bot()` can admit a call:
   - `NXLYR_TURN_MODE`: unset means `smart_backstop`; allowed values are `smart_backstop` and `speech_timeout`. Any other non-empty value is a startup error.
   - `NXLYR_TURN_BACKSTOP_SECS`: unset means `0.8`; it must parse as a finite decimal in the inclusive range `0.3` through `2.0`. Invalid, non-finite, or out-of-range values are startup errors.
   - Startup errors must name the variable, the received value where safe, and the allowed values/range. They must abort process initialization so an invalid image fails its container health check immediately; they must not be deferred to call setup or silently select a default.

2. `smart_backstop` builds this ordered stop list:
   - `TurnAnalyzerUserTurnStopStrategy(LocalSmartTurnAnalyzerV3(params=SmartTurnParams(stop_secs=backstop_secs + 0.2)))`, then
   - `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=backstop_secs)`.

   `backstop_secs` is the validated `NXLYR_TURN_BACKSTOP_SECS` value. The Smart Turn guard must always be at least `0.2` seconds larger than the timer; reject configuration at startup if that invariant is not true. The timer starts after the VAD stop event and, with the unchanged `0.2` s VAD window, the default targets about `1.0` s of measured `user_turn_secs`. The builder must retain `wait_for_transcript=True` behavior and test with a finalized transcript; it must not silently change transcript handling.

3. `speech_timeout` builds exactly one `SpeechTimeoutUserTurnStopStrategy(user_speech_timeout=0.6)`, preserving its normal transcript requirement. It is intentionally an A/B comparison mode, not the default; `NXLYR_TURN_BACKSTOP_SECS` does not alter this mode.

4. The VAD analyzer and the existing VAD/transcription start strategies are left byte-for-byte behaviorally equivalent.

5. The two stop strategies are deliberately independent. In Pipecat 1.5.0, both return `ProcessFrameResult.CONTINUE`; each may emit `on_user_turn_stopped`. `UserTurnController._trigger_user_turn_stop()` accepts the first event for an active, non-speaking turn, sets `_user_turn=False`, and resets every stop strategy. Thus either strategy can release the turn; a later event is ignored as a duplicate. This is verified below, not assumed.

### Source re-check (not inherited from the audit)

Checked against current `agent/bot.py` in this worktree and the local main-checkout venv, which reports `pipecat-ai 1.5.0`:

| Check | Result | Functions and line ranges checked |
| --- | --- | --- |
| Required imports resolve in local Pipecat 1.5.0 | VERIFIED | `from pipecat.turns.user_stop import SpeechTimeoutUserTurnStopStrategy, TurnAnalyzerUserTurnStopStrategy`; `from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3`; `from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams`. Direct import commands produced each class's module-qualified name. |
| Current implicit default is Smart Turn v3 | VERIFIED | `agent/bot.py:83-87,467-496`; imported `UserTurnStrategies` / `default_user_turn_stop_strategies` from `pipecat.turns.user_turn_strategies`; source at `43-51,74-78`. |
| With `stop=[TurnAnalyzerUserTurnStopStrategy(...), SpeechTimeoutUserTurnStopStrategy(...)]`, the first stop event releases the active turn | VERIFIED | Imported `UserTurnController`, `ProcessFrameResult`, and both stop strategies. `UserTurnController.process_frame()` `149-179` evaluates the list; both strategy `process_frame()` methods return `CONTINUE` at `TurnAnalyzerUserTurnStopStrategy` `126-151` and `SpeechTimeoutUserTurnStopStrategy` `123-147`. Their stop events reach `UserTurnController._trigger_user_turn_stop()` `314-337`, which finalizes once and resets all stop strategies at `330-335`; a later event is rejected at `317-319`. |
| `SmartTurnParams(stop_secs=...)` reaches `LocalSmartTurnAnalyzerV3` | VERIFIED | Imported both classes. `LocalSmartTurnAnalyzerV3.__init__()` `35-44` forwards `**kwargs` to `BaseSmartTurn.__init__()`; `BaseSmartTurn.__init__()` `60-70` accepts `params: SmartTurnParams` and derives `_stop_ms`. `SmartTurnParams.stop_secs` is declared at `32-43`; local construction of `SmartTurnParams(stop_secs=1.0)` succeeded. |
| Why the audit's three-second stall occurs | VERIFIED | Imported `BaseSmartTurn` and `EndOfTurnState`. `BaseSmartTurn.append_audio()` `119-151` returns COMPLETE after `_silence_ms >= _stop_ms`; defaults are `STOP_SECS = 3` and `SmartTurnParams.stop_secs = STOP_SECS` at `26-43`. `TurnAnalyzerUserTurnStopStrategy._handle_vad_user_stopped_speaking()` `187-225` leaves `_turn_complete=False` for an INCOMPLETE verdict; `_maybe_trigger_user_turn_stopped()` returns early at `279-315`. |
| Pipecat installed in `nxlyr_agent` versus local venv | UNVERIFIED for the running container; VERIFIED locally as `pipecat-ai 1.5.0` | Local command: `agent/venv/bin/python -c 'import importlib.metadata as m; print(m.version("pipecat-ai"))'`. The running container was not inspected. Before real calls, the human runs the read-only container command in the Exit test. |

## Data touched (none expected; never execute SQL)

Implementation and automated tests touch no persistent data: no Supabase, migrations, SQL, or Redis. Tests use only in-memory fakes and fake time. The human-only real-call exit test uses the existing opt-in latency CSV and temporarily writes then deletes the existing Redis `demo:config` cap override exactly as specified below. Never execute SQL.

## Acceptance tests (automated)

Run from this worktree, using the main checkout's existing venv:

```bash
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"
PY="$MAIN/agent/venv/bin/python"
"$PY" -m unittest agent.test_turn_release
(cd agent && "$PY" -c "import bot, week2_latency_observer")
```

- [ ] Default/unset process-start configuration selects `smart_backstop`, `backstop_secs=0.8`, and an ordered stop list: Smart Turn v3 first, timeout second. Smart Turn receives `SmartTurnParams(stop_secs=1.0)` and the timeout receives `user_speech_timeout=0.8`.
- [ ] `NXLYR_TURN_BACKSTOP_SECS=1.2` at process start produces a `1.2` s timeout and Smart Turn `stop_secs=1.4`; boundary values `0.3` and `2.0` are accepted.
- [ ] Invalid `NXLYR_TURN_BACKSTOP_SECS` values (non-numeric, non-finite, below `0.3`, above `2.0`) and any broken `smart_turn_stop_secs >= backstop_secs + 0.2` invariant raise a clear process-start configuration error. No call setup is required to observe the error.
- [ ] `NXLYR_TURN_MODE=speech_timeout` creates exactly one `SpeechTimeoutUserTurnStopStrategy` with `user_speech_timeout=0.6`; it does not construct Smart Turn and is unaffected by a valid `NXLYR_TURN_BACKSTOP_SECS` override.
- [ ] An invalid non-empty `NXLYR_TURN_MODE` raises a clear process-start configuration error naming the variable and allowed values. A module/process startup test proves the error occurs before `run_bot()` is called, so a bad production environment fails container health rather than dropping a later call.
- [ ] With a fake analyzer forced to return `EndOfTurnState.INCOMPLETE`, a finalized fake transcript, and continuous silence after VAD stop, the `smart_backstop` controller emits exactly one semantic `UserStoppedSpeakingFrame` at the fake clock's `0.8` s timer deadline. It must not wait for Smart Turn's original three-second default.
- [ ] With the same forced-INCOMPLETE analyzer, a caller resumes speaking before the fake clock reaches `0.8` s. The timeout is cancelled/reset, no `UserStoppedSpeakingFrame` is emitted during that mid-sentence pause, and a later genuine final pause releases exactly once.
- [ ] In `speech_timeout` mode, a pause shorter than its `0.6` s timer does not release early; a finalized transcript followed by a longer final pause releases exactly once.
- [ ] Timing tests use an injected fake clock/task scheduler that replaces the strategy module's sleep with an advanceable awaitable. They use no wall-clock sleeps; the only tolerance is one explicit event-loop drain after each `clock.advance()`, documented in the test helper. The asserted deadlines are fake-clock values, so CI load cannot create timing flakes.
- [ ] The existing backend tests remain runnable; known unrelated `agent.test_kb_loader` failures are not suppressed, deleted, or treated as caused by this task.

## Exit test (what I do by hand on real calls, with exact commands)

`NXLYR_LATENCY_CSV=/app/section6_real_call.csv` is already enabled in production. Establish an old-code baseline before merge, copy it off the VPS before deployment recreates the agent and resets its in-container CSV, then run the same batch after deployment. The report runs on the founder's Mac and is not a repository artifact.

The spoken script for every call is identical: a normal completed sentence, a deliberate mid-sentence pause shorter than `0.8` s, then a completed continuation. Make all calls serially and record any bot cut-off by ear.

1. 🧑 YOU — Before merge, on the VPS running the old code, verify the running Pipecat version and raise demo caps only for the baseline batch:

   ```bash
   cd /opt/nxlyr
   docker compose exec -T agent python -c 'import importlib.metadata as m; print(m.version("pipecat-ai"))'
   docker compose exec -T redis redis-cli HSET demo:config phone_limit 100 ip_limit 100 phone_cooldown_seconds 5 ip_cooldown_seconds 5
   BASELINE_BEFORE="$(docker compose exec -T agent sh -c 'if [ -f /app/section6_real_call.csv ]; then tail -n +2 /app/section6_real_call.csv | wc -l; else echo 0; fi' | tr -d '[:space:]')"
   printf 'Baseline data rows before old-code calls: %s\n' "$BASELINE_BEFORE"
   ```

   Expected Pipecat version: `1.5.0`. If it differs, stop: do not use the local-source conclusions above as proof for the container.

2. 🧑 YOU — Place 10 consented baseline calls using that script, then remove the temporary cap override and copy the CSV out of the container before any merge/deploy:

   ```bash
   cd /opt/nxlyr
   docker compose exec -T redis redis-cli DEL demo:config
   docker compose cp agent:/app/section6_real_call.csv ./section6_real_call-baseline.csv
   printf '%s\n' "$BASELINE_BEFORE" > ./section6_real_call-baseline-before.txt
   ```

3. 🧑 YOU — On the Mac, copy the baseline from the VPS and report only the old-code rows added after `BASELINE_BEFORE`. Replace `VPS_HOST` with the founder's VPS hostname or IP; this does not expose any secret.

   ```bash
   mkdir -p ~/Downloads/nxlyr-f07-r2
   scp "root@VPS_HOST:/opt/nxlyr/section6_real_call-baseline.csv" ~/Downloads/nxlyr-f07-r2/section6_real_call-baseline.csv
   scp "root@VPS_HOST:/opt/nxlyr/section6_real_call-baseline-before.txt" ~/Downloads/nxlyr-f07-r2/section6_real_call-baseline-before.txt
   BASELINE_BEFORE="$(tr -d '[:space:]' < ~/Downloads/nxlyr-f07-r2/section6_real_call-baseline-before.txt)"
   python3 /Users/vansh/Desktop/SALES\ AGENT/nxlyr/latency_report.py ~/Downloads/nxlyr-f07-r2/section6_real_call-baseline.csv --skip-first "$BASELINE_BEFORE"
   ```

   Record the baseline report's `roundtrip_ms` p50, p90, and p95, its exact F07 line, and all by-ear cut-off notes.

4. 🧑 YOU — After the approved code is merged by the human, deploy the merged code using the required pair. This deployment recreates the agent and resets its in-container CSV; it does not require an `.env` edit for `NXLYR_LATENCY_CSV`:

   ```bash
   cd /opt/nxlyr
   git pull origin main
   docker compose up -d --build
   docker compose ps agent
   sleep 5
   docker compose ps agent
   AFTER_BEFORE="$(docker compose exec -T agent sh -c 'if [ -f /app/section6_real_call.csv ]; then tail -n +2 /app/section6_real_call.csv | wc -l; else echo 0; fi' | tr -d '[:space:]')"
   test "$AFTER_BEFORE" = 0
   ```

5. 🧑 YOU — Raise caps for the after batch:

   ```bash
   cd /opt/nxlyr
   docker compose exec -T redis redis-cli HSET demo:config phone_limit 100 ip_limit 100 phone_cooldown_seconds 5 ip_cooldown_seconds 5
   ```

   Place the same 10 consented scripted calls. Then remove the cap override and copy the new CSV out of the container:

   ```bash
   cd /opt/nxlyr
   docker compose exec -T redis redis-cli DEL demo:config
   docker compose cp agent:/app/section6_real_call.csv ./section6_real_call-after.csv
   ```

6. 🧑 YOU — On the Mac, copy and report the after batch. Because the deployment reset the CSV and `AFTER_BEFORE` is asserted as `0`, do not skip any data rows:

   ```bash
   scp "root@VPS_HOST:/opt/nxlyr/section6_real_call-after.csv" ~/Downloads/nxlyr-f07-r2/section6_real_call-after.csv
   python3 /Users/vansh/Desktop/SALES\ AGENT/nxlyr/latency_report.py ~/Downloads/nxlyr-f07-r2/section6_real_call-after.csv
   ```

   Record the after report's `roundtrip_ms` p50, p90, and p95, its exact F07 line, and all by-ear cut-off notes.

   Pass when the after F07 line is `0 of N` for `user_turn_secs >= 2.5 s`, after `roundtrip_ms` p95 is lower than baseline, and by-ear cut-offs are not worse than baseline. The greeting has no `user_turn_secs` and is not part of `N`. If the old-code baseline F07 line already reports `0` stalls, state that fact and judge the comparison by cut-offs only; do not claim a stall reduction from that run.

## Risks and rollback

| Risk | Mitigation / rollback |
| --- | --- |
| A 0.8 s post-VAD timer can cut off unusually slow speakers. | The required mid-sentence-pause unit test and 10-call by-ear test specifically exercise this. If it occurs, immediately set `NXLYR_TURN_MODE=speech_timeout` for the controlled comparison or revert the task commit; do not alter VAD or Deepgram as an unreviewed workaround. |
| Deepgram finalization arrives after the timer or never arrives. | Retain `wait_for_transcript=True`; test the intended finalized-transcript path. A missing transcript is never silently converted into LLM input; the framework's existing five-second watchdog remains the final fail-safe. |
| Local Pipecat and deployed image differ. | Run the read-only package-version command before exit testing. A result other than 1.5.0 blocks deployment/field conclusions until the installed source is re-checked. |
| The shared latency CSV includes earlier rows or mixes concurrent calls. | Snapshot and copy the old-code baseline count, make calls serially, report its rows with `--skip-first "$BASELINE_BEFORE"`, and assert the post-deploy CSV count is zero before the after batch. |
| Environment switch is malformed. | Fail immediately at process startup with a named validation error; do not admit calls. |
| Controlled comparison needs to change mode. | Flipping mode is a human `.env` edit followed by `docker compose up -d`, which recreates the agent. Reverting code is `git revert <task-commit>` on the source branch, then the VPS `git pull origin main` and `docker compose up -d --build` pair. |

## Follow-ups

- The transcript-safety decision is final for this task: never release without a final transcript; retain Pipecat's five-second watchdog.
- A watchdog release can be made visible without logging caller content: Pipecat's `UserTurnController._user_turn_stop_timeout_task_handler()` emits `on_user_turn_stop_timeout` before finalizing the turn. A later, separate observability task can attach application-owned handling that logs a fixed event/counter such as `turn_watchdog_release` with mode and elapsed time only—never transcript text, audio, phone numbers, or call IDs. Do not implement this logging in F07.
- The real-call driver remains deliberately out of scope; the approved spoken script is the test harness.
