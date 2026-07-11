"""
Quick .env sanity check — confirms python-dotenv finds and loads your .env
file correctly, before running the full test_pipeline.py.

Run from the same folder as your .env file:
    python3 check_dotenv.py
"""

import os
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(".env")

print(f"Looking for .env at: {ENV_PATH.resolve()}")

if not ENV_PATH.exists():
    print("[FAIL] No .env file found in the current directory.")
    print("       Make sure you're running this from the same folder as .env,")
    print("       and that the file is literally named '.env' (not '.env.txt').")
else:
    print("[PASS] .env file found.")

loaded = load_dotenv(dotenv_path=ENV_PATH, override=True)
print(f".env parsed successfully: {loaded}")

REQUIRED = ["DEEPGRAM_API_KEY", "OPENAI_API_KEY", "ELEVENLABS_API_KEY"]
OPTIONAL = ["ELEVENLABS_VOICE_ID"]

print("\n-- Required keys --")
all_present = True
for key in REQUIRED:
    value = os.getenv(key)
    if value:
        masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
        print(f"[PASS] {key} = {masked}")
    else:
        print(f"[FAIL] {key} is missing or empty")
        all_present = False

print("\n-- Optional keys --")
for key in OPTIONAL:
    value = os.getenv(key)
    if value:
        print(f"[SET]  {key} = {value}")
    else:
        print(f"[SKIP] {key} not set (will fall back to default voice)")

print("\n======================================")
if all_present:
    print("All required keys loaded correctly. Safe to run test_pipeline.py.")
else:
    print("Missing required key(s) above — fix .env before running test_pipeline.py.")
print("======================================")
