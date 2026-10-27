# v4 probe: a 200 means "accepted or ignored", not "used"; dropping style and speed on v4 is correct

- `agent/voice_config.py` `V4_DROPPABLE` (style, speed, use_speaker_boost, optimize_streaming_latency) are not sent on any `eleven_v4*` model; the call log says `dropped=`.
- The founder's v4 probe (019 exit test) got a 200 for `previous_text`, stability, similarity, style, speed and speaker boost, and a 400 `unsupported_model` for `optimize_streaming_latency`. A 200 only shows the request was accepted or ignored, not that the setting changed the audio. The only proven rejection is `optimize_streaming_latency`.
- ElevenLabs' "What is Eleven v4" help page says "Style and Speed sliders are not available in Eleven v4", so the drop is correct. No follow-up task unless a future test shows style or speed audibly working on v4.
- Source: `agent/voice_config.py:30`, `docs/issues/019-voice-config.md`; probe result per the founder, 2026-10-27, not verified by an agent; help-page quote as fetched for spec 019.
