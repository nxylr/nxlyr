# F09: pipecat's own DEBUG lines print phone numbers and the prompt

- `pipecat/runner/utils.py:276` (DEBUG, once per call) prints the Exotel handshake including the full `from` and `to` phone numbers.
- `pipecat/services/openai/base_llm.py:304-306` (DEBUG, every LLM call) prints the whole context including the system prompt, which embeds the KB.
- Verified locally with pipecat 1.5.0 and fake data, by running pipecat's own functions through an old-style default handler.
- Because production runs DEBUG (see `2026-10-22-f09-production-logs-at-debug.md`), both are expected to be live. UNVERIFIED there until exit-test Batch A.
- Source: `docs/issues/004-f09-log-hygiene.md`, `.agent/reports/review-1.md`.
