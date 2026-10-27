# ElevenLabs voice settings are unset; text normalisation is off

- Stability, similarity_boost, style, use_speaker_boost and speed were all unset until task 019 (PR #45). They can now be set per call in Redis `voice:config` (`agent/voice_config.py`); with no override nothing is sent, as before.
- Flash v2.5 ships with text normalisation off, and only enterprise accounts can enable `apply_text_normalization`, so spoken-form text (amounts, dates, percentages) has to come from our own data and prompt. See `2026-10-24-kb-digits-read-aloud-crore-mispronounced.md`.
- Source: founder research notes 2026-10-24 (the ElevenLabs plan limits are not re-checked by an agent); voice settings reference: https://github.com/elevenlabs/skills/blob/main/text-to-speech/references/voice-settings.md. Whether Flash honours these settings is open: see `2026-10-24-elevenlabs-voice-settings-unverified-on-flash.md`.
