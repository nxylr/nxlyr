# /health is not a usable external health check — 2026-10-13

- /health returns an nginx 404 externally; don't use it as a health check; the real gate is a real call.
- Source: observed by the human during the F01 evidence call (task 001). UNVERIFIED by an agent.
