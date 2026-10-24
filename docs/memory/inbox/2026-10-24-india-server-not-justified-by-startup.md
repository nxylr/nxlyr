# A server in India cannot be justified by start-up time

- Start-up time is dominated by Exotel's bridging between pickup and our WebSocket (3.1 to 3.4 s of 3.89 to 4.3 s on the 015 exit calls), and that happens before the call reaches our server. Moving the server does not shorten it.
- The case for an India server has to rest on the per-turn round trips to Exotel, OpenAI, Deepgram and ElevenLabs. Measure those first, per hop, from the current VPS; only then compare.
- Source: reasoning from the 015 exit figures (`log.md`), the founder's decision on 2026-10-24. Not a measured comparison of regions.
