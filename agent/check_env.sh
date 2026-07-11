#!/usr/bin/env bash
# NXLYR agent — dev environment health check
# Verifies the Python/venv setup, the pyexpat/expat fix, portaudio, and that
# pipecat + its service SDKs actually import. Run this from inside the venv:
#
#   source venv/bin/activate
#   bash check_env.sh
#
# Exits 0 if everything passes, 1 if anything fails (safe to use in CI too).

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

pass() { echo -e "${GREEN}[PASS]${NC} $1"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $1"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[SKIP]${NC} $1"; }

echo "== 1. Virtual environment sanity =="

if [ -z "$VIRTUAL_ENV" ]; then
    fail "No venv active (\$VIRTUAL_ENV is empty). Run: source venv/bin/activate"
else
    pass "Venv active: $VIRTUAL_ENV"
fi

PY_PATH="$(command -v python3)"
PIP_PATH="$(command -v pip)"

if [[ "$PY_PATH" == "$VIRTUAL_ENV"* ]]; then
    pass "python3 resolves inside venv ($PY_PATH)"
else
    fail "python3 resolves OUTSIDE venv ($PY_PATH) — check for a stacked/nested activation"
fi

if [[ "$PIP_PATH" == "$VIRTUAL_ENV"* ]]; then
    pass "pip resolves inside venv ($PIP_PATH)"
else
    fail "pip resolves OUTSIDE venv ($PIP_PATH) — check for a stacked/nested activation"
fi

echo ""
echo "== 2. Python version =="

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [ "$PY_VER" == "3.12" ]; then
    pass "Python version is 3.12 ($(python3 --version 2>&1))"
else
    fail "Expected Python 3.12, got $PY_VER"
fi

echo ""
echo "== 3. macOS pyexpat / libexpat fix =="

if python3 -c "import pyexpat" 2>/dev/null; then
    pass "pyexpat imports cleanly"
else
    fail "pyexpat import failed — the install_name_tool/codesign fix did not stick"
fi

if command -v brew >/dev/null 2>&1; then
    if brew list expat >/dev/null 2>&1; then
        pass "Homebrew 'expat' formula installed"
    else
        fail "Homebrew 'expat' formula not found"
    fi

    echo ""
    echo "== 4. portaudio (needed for local pyaudio dev builds) =="
    if brew list portaudio >/dev/null 2>&1; then
        pass "Homebrew 'portaudio' formula installed"
    else
        fail "Homebrew 'portaudio' formula not found — pyaudio wheel build will fail"
    fi
else
    warn "Homebrew not found — skipping brew checks (expected on Linux/production)"
fi

echo ""
echo "== 5. pipecat-ai package =="

PIPECAT_VER="$(pip show pipecat-ai 2>/dev/null | awk -F': ' '/^Version/{print $2}')"
if [ -n "$PIPECAT_VER" ]; then
    pass "pipecat-ai installed (version $PIPECAT_VER)"
else
    fail "pipecat-ai not found via pip show"
fi

if python3 -c "import pipecat" 2>/dev/null; then
    pass "import pipecat succeeds"
else
    fail "import pipecat failed"
fi

echo ""
echo "== 6. Service SDKs (deepgram, openai, silero/onnx, local audio) =="

check_import() {
    # $1 = module name to import, $2 = human label
    if python3 -c "import $1" 2>/dev/null; then
        pass "$2 importable ('import $1')"
    else
        fail "$2 NOT importable ('import $1')"
    fi
}

check_import "deepgram"     "Deepgram SDK"
check_import "openai"       "OpenAI SDK"
check_import "onnxruntime"  "ONNX Runtime (used by Silero VAD)"
check_import "numpy"        "NumPy"
check_import "pyaudio"      "PyAudio (local mic/speaker I/O — dev-machine only)"

echo ""
echo "======================================"
echo -e "Result: ${GREEN}${PASS} passed${NC}, ${RED}${FAIL} failed${NC}"
echo "======================================"

if [ "$FAIL" -gt 0 ]; then
    exit 1
else
    exit 0
fi
