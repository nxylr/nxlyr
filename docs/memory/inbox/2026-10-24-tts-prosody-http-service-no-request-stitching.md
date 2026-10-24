# TTS prosody: the HTTP service re-invents intonation for every sentence

- We use `ElevenLabsHttpTTSService`, which makes a separate HTTP request per sentence, so ElevenLabs picks the intonation each time with no memory of the previous sentence. Pipecat's docs recommend the WebSocket service for interactive conversations. ElevenLabs has request stitching (`previous_request_ids`) for exactly this, but Pipecat does not expose it.
- Candidate cause of the random tone between sentences and of call 15's closing line having no falling tone. Needs its own research task and spec.
- Cautions: the WebSocket service narrows speed to 0.7 to 1.2, and `apply_text_normalization` needs a reconnect. Earlier, the WebSocket service went unhealthy after the first turn on this Hetzner/Docker setup (comment in `agent/bot.py`), which is why HTTP was chosen.
- Sources (founder research, 2026-10-24; not re-checked by an agent):
  - Pipecat ElevenLabs TTS service: https://docs.pipecat.ai/api-reference/server/services/tts/elevenlabs.md (the HTTP service makes a separate request per piece of text; the WebSocket service is the one recommended for interactive conversations).
  - ElevenLabs request stitching: https://elevenlabs.io/docs/api-reference/how-to-use-request-stitching (`previous_request_ids`, ids under two hours old, not available on `eleven_v3`).
- Evidence on our side: 014 exit test call 15 (closing line without a falling tone). Related: the L3 TTS test in `docs/baselines/2026-10-22-baseline.md`.
