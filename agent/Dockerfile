# NXLYR — Exotel telephony server (Week 3 / Task 2.5)
#
# This file replaces the Week 2 Dockerfile outright rather than editing it. That
# one built a latency harness: Ubuntu 24.04, portaudio, and a userspace
# PulseAudio server with a null-sink virtual mic, so test_pipeline.py could talk
# to fake audio devices. None of that applies here — every byte of audio in this
# container arrives and leaves over a WebSocket, so there is no sound card, real
# or virtual, to stand up.

FROM python:3.12-slim

# libgomp1: kept as insurance for the native-extension stack, NOT because a
#   failure was observed here. Debian slim ships no libgomp, and older
#   onnxruntime builds link libgomp.so.1 — that combination is the classic
#   "libgomp.so.1: cannot open shared object file" crash on first import, and
#   it's what this guards against.
#
#   Measured 2026-08-03 against what we actually pin: onnxruntime 1.24.4 imports
#   fine on bare python:3.12-slim with no libgomp1, on BOTH arm64 and amd64. So
#   for onnxruntime specifically this package is currently redundant.
#
#   It stays anyway, for 360 kB: the rest of the native stack (numba/llvmlite,
#   scipy, resampy) has not been verified without it, and the amd64 deploy target
#   has only ever been probed, never fully built. Revisit once the VPS build has
#   run green — this is a cheap hedge, not a diagnosed requirement.
#
#   This is the only OS package the server needs; everything else in
#   requirements.txt installs from wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# PYTHONUNBUFFERED: loguru and uvicorn write straight through to `docker logs`
#   instead of sitting in a pipe buffer until the container dies.
# PYTHONDONTWRITEBYTECODE: no .pyc litter in an image layer.
# HOST/PORT: same defaults as server.py's __main__ block, so running the module
#   directly and running the container behave identically.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOST=0.0.0.0 \
    PORT=7860

WORKDIR /app

# Dependencies in their own layer, above the source copy. Everything below this
# line changes on most commits; this layer only rebuilds when requirements.txt
# itself does.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the three modules the server actually loads. week2_latency_observer.py is
# imported lazily by bot.py and only when NXLYR_LATENCY_CSV is set — but it has
# to be in the image, or enabling that env var would ImportError mid-call
# instead of at boot.
COPY bot.py server.py week2_latency_observer.py ./

# Drop root. Nothing here writes to the filesystem in normal operation; if the
# latency observer is ever enabled in a container it needs a writable path, so
# point NXLYR_LATENCY_CSV at a mounted volume rather than at /app.
RUN useradd --create-home --uid 10001 nxlyr && chown -R nxlyr:nxlyr /app
USER nxlyr

# Documentation only, and only accurate at the default PORT — EXPOSE cannot read
# an env var set at runtime. The real port mapping is docker-compose's job.
EXPOSE 7860

# Hits server.py's GET /health, which returns a flat {"status": "ok"} and touches
# no third-party service — so this reports on us, not on Deepgram's uptime. Done
# with urllib instead of curl to avoid adding curl to the image.
#
# Caveat worth knowing before wiring a restart policy to this: the check shares
# the event loop with live calls. start-period is generous because importing
# onnxruntime and the pipecat service stack is not fast.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT','7860') + '/health', timeout=8)"]

# sh -c so $HOST/$PORT expand; exec so uvicorn becomes PID 1 and receives
# SIGTERM directly, letting in-flight calls shut down instead of being killed.
CMD ["sh", "-c", "exec uvicorn server:app --host \"$HOST\" --port \"$PORT\""]
