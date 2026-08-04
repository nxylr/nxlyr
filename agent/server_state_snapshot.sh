#!/usr/bin/env bash
# Read-only. Run this BEFORE starting the test, and again AFTER teardown.
# The two outputs should be identical (aside from a noted Docker base-image
# caveat below) — that identity is your proof, not just our word for it,
# that nxlyr_redis and the /opt/nxlyr compose project were never touched
# and nothing was left behind.
#
# Usage:
#   ./server_state_snapshot.sh > snapshot_before.txt
#   ...(run the full test)...
#   ./server_state_snapshot.sh > snapshot_after.txt
#   diff snapshot_before.txt snapshot_after.txt

echo "===== Server state snapshot: $(date -u +'%Y-%m-%dT%H:%M:%SZ') ====="
echo
echo "--- docker ps -a ---"
docker ps -a
echo
echo "--- docker images ---"
docker images
echo
echo "--- docker compose projects ---"
docker compose ls 2>/dev/null || echo "none / not available"
echo
echo "--- disk (/) ---"
df -h /
echo
echo "--- memory ---"
free -h
echo
echo "--- ufw ---"
ufw status 2>/dev/null || echo "ufw not active or not available"
echo
echo "===== end snapshot ====="
