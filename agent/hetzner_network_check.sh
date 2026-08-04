#!/usr/bin/env bash
# Network-only latency floor check. No Docker needed — this is just `curl`,
# which is effectively always present on Ubuntu and touches nothing on the
# host beyond making a few outbound HTTPS requests. Safe to run directly.
#
# Needs: OPENAI_API_KEY, DEEPGRAM_API_KEY, ELEVENLABS_API_KEY in the shell
# environment (export them first — do NOT put them in a permanent file on
# this box unless you mean to).

if ! command -v curl >/dev/null 2>&1; then
  echo "curl not found. Install with: sudo apt install -y curl"
  echo "(curl is about as standard/low-risk a package as exists on Ubuntu.)"
  exit 1
fi

FMT='  connect=%{time_connect}s  tls=%{time_appconnect}s  ttfb=%{time_starttransfer}s  total=%{time_total}s\n'

echo "== OpenAI =="
for i in 1 2 3; do
  curl -s -o /dev/null -w "$FMT" \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" \
    https://api.openai.com/v1/models
done

echo "== Deepgram =="
for i in 1 2 3; do
  curl -s -o /dev/null -w "$FMT" \
    -H "Authorization: Token ${DEEPGRAM_API_KEY}" \
    https://api.deepgram.com/v1/projects
done

echo "== ElevenLabs =="
for i in 1 2 3; do
  curl -s -o /dev/null -w "$FMT" \
    -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
    https://api.elevenlabs.io/v1/voices
done

echo
echo "Compare 'ttfb' here against the Delhi run's floor (~350ms OpenAI,"
echo "~900ms-1s Deepgram REST, ~450-700ms ElevenLabs). A Luxembourg box"
echo "should show dramatically lower numbers if geography was the driver."
