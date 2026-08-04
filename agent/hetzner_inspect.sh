#!/usr/bin/env bash
# READ-ONLY baseline inspection. Makes ZERO changes to the server — no sudo,
# no installs, no modprobe. Only queries and reports what already exists.
#
# Why this runs first: to test the pipeline headlessly we need a virtual
# mic (ALSA loopback) and a few packages (portaudio, alsa-utils). Whether
# those already exist on this box determines exactly what the setup script
# should install and exactly what the teardown script should remove —
# nothing more, nothing less. Skipping this step risks either polluting
# the server permanently, or a "cleanup" that removes something that was
# already there before we ever touched the box.
#
# Usage:
#   chmod +x hetzner_inspect.sh
#   ./hetzner_inspect.sh
#
# Paste the full output (or the saved hetzner_baseline_report.txt) back —
# that's what the next set of scripts gets built against.

set -uo pipefail

OUT="hetzner_baseline_report.txt"

{
echo "===== Hetzner baseline report ====="
echo "Generated: $(date -u +'%Y-%m-%dT%H:%M:%SZ')"
echo

echo "--- OS / Kernel ---"
cat /etc/os-release 2>/dev/null || echo "no /etc/os-release found"
echo "kernel: $(uname -r)"
echo "arch:   $(uname -m)"
echo

echo "--- CPU / Memory / Disk ---"
echo "cores: $(nproc 2>/dev/null || echo unknown)"
free -h 2>/dev/null || echo "free: not available"
df -h / 2>/dev/null || echo "df: not available"
echo

echo "--- Python ---"
python3 --version 2>&1 || echo "python3: not found"
if python3 -m venv --help >/dev/null 2>&1; then
  echo "python3-venv: available"
else
  echo "python3-venv: NOT available"
fi
python3 -m pip --version 2>&1 || echo "pip: not found"
echo

echo "--- Relevant packages (dpkg) — pre-existing install status ---"
for pkg in portaudio19-dev libportaudio2 alsa-utils python3-venv python3-pip docker.io docker-ce; do
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    ver=$(dpkg -s "$pkg" 2>/dev/null | awk -F': ' '/^Version/{print $2}')
    echo "  [INSTALLED]     $pkg ($ver)"
  else
    echo "  [not installed] $pkg"
  fi
done
echo

echo "--- ALSA / sound state, BEFORE any changes ---"
echo "snd_aloop currently loaded?"
lsmod 2>/dev/null | grep -i snd_aloop || echo "  not currently loaded"
echo "is snd-aloop available in this kernel at all?"
modinfo snd-aloop 2>&1 | head -5
echo "existing playback devices (aplay -l):"
aplay -l 2>&1
echo "existing capture devices (arecord -l):"
arecord -l 2>&1
echo

echo "--- Docker (alternate isolation option) ---"
if command -v docker >/dev/null 2>&1; then
  echo "  docker present: $(docker --version 2>&1)"
else
  echo "  docker: not present"
fi
echo

echo "--- Test-directory collision check ---"
for d in "$HOME/nxlyr-test" "$HOME/nxlyr-hetzner-test"; do
  if [ -e "$d" ]; then
    echo "  !  $d already exists — will need a different name for our test dir"
  else
    echo "  ok: $d does not exist yet"
  fi
done
echo

echo "--- Running services (top 20, awareness only) ---"
systemctl list-units --type=service --state=running 2>/dev/null | head -20 || echo "  systemctl not available"
echo

echo "===== end of report ====="
} | tee "$OUT"

echo
echo "Saved to: $OUT"
echo "Nothing on this server was changed. Paste the report content back."
