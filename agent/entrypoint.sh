#!/usr/bin/env bash
# Runs entirely inside the container. Starts a userspace PulseAudio server,
# builds a virtual mic (a null-sink + a source remapped from its monitor),
# runs test_pipeline.py against it, plays the WAV prompts into it one at a
# time, then copies results to /app/results (a host-mounted volume) so they
# survive after the container exits.

set -uo pipefail

echo "Starting PulseAudio (userspace, container-local only)..."
pulseaudio -D --exit-idle-time=-1 --disallow-exit --log-target=stderr
sleep 2

echo "Creating virtual mic/speaker..."
pactl load-module module-null-sink sink_name=fakemic sink_properties=device.description=FakeMic
pactl load-module module-remap-source master=fakemic.monitor source_name=fakemic_source source_properties=device.description=FakeMicSource
pactl set-default-source fakemic_source
pactl set-default-sink fakemic

echo "Devices now visible to PulseAudio:"
pactl list short sinks
pactl list short sources

WAV_DIR="/app/wavs"
GAP="${GAP_SECONDS:-8}"
RESULTS_DIR="/app/results"
mkdir -p "$RESULTS_DIR"

echo "Starting the pipeline in the background..."
python3 test_pipeline.py > "$RESULTS_DIR/pipeline_stdout.log" 2>&1 &
PIPELINE_PID=$!
sleep 5   # let it finish startup / the opening greeting before we speak

shopt -s nullglob
files=("$WAV_DIR"/*.wav)
if [ ${#files[@]} -eq 0 ]; then
  echo "No WAV files found in $WAV_DIR — nothing to play. Check the build context."
else
  echo "Playing ${#files[@]} prompt(s), ${GAP}s gap between each."
  i=0
  for f in "${files[@]}"; do
    i=$((i + 1))
    if ! kill -0 "$PIPELINE_PID" 2>/dev/null; then
      echo "Pipeline process exited early — stopping playback. Check pipeline_stdout.log."
      break
    fi
    echo "[$i/${#files[@]}] $f"
    paplay --device=fakemic "$f"
    sleep "$GAP"
  done
fi

echo "Stopping pipeline..."
kill "$PIPELINE_PID" 2>/dev/null || true
wait "$PIPELINE_PID" 2>/dev/null || true

echo "Copying results to $RESULTS_DIR ..."
cp -v week2_latency.csv "$RESULTS_DIR/" 2>/dev/null || echo "  no week2_latency.csv produced"
cp -v week2_latency_events.log "$RESULTS_DIR/" 2>/dev/null || echo "  no week2_latency_events.log produced"

echo "Done. Results are in the mounted results/ folder on the host."
