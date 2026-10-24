# Questions for Exotel: 3.1 to 3.4 s between pickup and our WebSocket

- On the three 015 exit calls the stopwatch (pickup to first word) was 3.89 to 4.3 s while our server needed 0.5 to 1.2 s from `ws_connected` to `first_bot_audio_sent`. The other 3.1 to 3.4 s is outside our code. It is a subtraction: how it splits between Exotel bridging, the WebSocket connect and phone-network playout is not measured.
- Ask Exotel:
  1. Why do 3.1 to 3.4 s pass between the caller answering and our WebSocket receiving audio?
  2. Does the voicebot applet have settings that shorten it?
  3. Why does the `start` message occasionally take about 550 ms? `handshake_ms`, which includes waiting for that message, was 138 / 553 / 136 on the three calls.
- Source: founder's 015 exit test, 2026-10-24 (`log.md`). Human action: send with the pending DND / 140xx question.
