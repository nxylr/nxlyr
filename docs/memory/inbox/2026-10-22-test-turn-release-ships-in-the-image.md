# `test_turn_release.py` ships in the image

- The Dockerfile has `COPY *.py ./`, so every `agent/test_*.py` module, including `test_turn_release.py`, is copied into the production image. Harmless, but test code is deployed.
- Source: `agent/Dockerfile` line 65; task 011 (PR #37).
