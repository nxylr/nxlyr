# Backchannel versus barge-in: any VAD speech start interrupts the bot

- On call 12 of the 014 exit test, on speaker, fan noise stopped the bot. Same cause as the 011 cough finding (`2026-10-23-speakerphone-cough-stops-the-bot.md`).
- `agent/bot.py:207-210` (`VADUserTurnStartStrategy(enable_interruptions=True)` and `TranscriptionUserTurnStartStrategy(enable_interruptions=True)`) treats any VAD speech start as an interruption, so an agreeing "haan" cuts the bot dead.
- Founder's view: the highest-value remaining change to how human it feels. Needs a spec (backchannel detection, minimum speech length, or interruption only after a transcript).
- Source: founder, 014 exit test 2026-10-24, call 12.
