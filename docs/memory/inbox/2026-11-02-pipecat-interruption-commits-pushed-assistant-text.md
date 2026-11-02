# Pipecat interruption commits pushed assistant text

- Fact: With the repository's Pipecat 1.5.0, an `InterruptionFrame` commits assistant text already pushed into the assistant aggregator before resetting it; if no text was pushed, no assistant message is added.
- Source: automated test `agent.test_bargein.AggregatorBehaviorTests.test_a8_interruption_commits_assistant_text_already_pushed`, run locally with the main checkout's Python environment on 2026-11-02.
- Limit: this proves aggregator behavior only. It does not prove how much of the committed text the caller heard over Exotel.
