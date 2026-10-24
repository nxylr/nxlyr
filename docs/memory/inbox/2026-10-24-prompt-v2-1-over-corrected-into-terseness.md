# Prompt v2 over-corrected into terseness; v2.1 needed

- By ear on the 014 exit test, 5 to 6 of 10 calls were natural (bar 7). The bot has no connectives at all, states a fact and stops, answers feel grudging, and every tail question is gone. "Hi Aarya" from the caller is not handled. Call 3 answered "that sounds expensive" with "hi my name is Aarya", a mid-call re-greeting that breaks the prompt's "never greet again".
- The distinction to encode in v2.1: content-free acknowledgements of the caller ("Great", "I see", "Fair question", "I hear you") stay banned; connectives ("So", "Okay so") and process phrases ("Let me check", "One second") become allowed, sparingly.
- The same change is the test for the first-sentence-wait hypothesis (see `2026-10-24-first-sentence-wait-145ms-after-prompt-v2.md`).
- Source: founder, 014 exit test 2026-10-24 (`docs/memory/log.md`).
