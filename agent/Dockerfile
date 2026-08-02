# Isolated environment for the Week 2 headless latency test.
# Everything lives in this image — nothing is installed on the host.
# Delete the image when done and the host is exactly as it was.

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# portaudio19-dev / build-essential: needed to build the PyAudio wheel
# pulseaudio + pulseaudio-utils: the virtual mic/speaker, entirely userspace
#   (no kernel module needed — this is why it works even though snd-aloop
#   isn't available on the host kernel)
# libasound2-plugins: gives ALSA apps (PyAudio uses ALSA on Linux) a "pulse"
#   backend, so they transparently talk to the PulseAudio virtual devices
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv build-essential \
    portaudio19-dev pulseaudio pulseaudio-utils libasound2-plugins \
    && rm -rf /var/lib/apt/lists/*

# Route ALSA's default device through PulseAudio
RUN mkdir -p /etc && printf 'pcm.!default {\n  type pulse\n}\nctl.!default {\n  type pulse\n}\n' > /etc/asound.conf

WORKDIR /app

COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

COPY test_pipeline.py week2_latency_observer.py analyze_week2.py ./
COPY wavs ./wavs
COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENTRYPOINT ["./entrypoint.sh"]
