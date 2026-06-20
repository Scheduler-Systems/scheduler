#!/usr/bin/env bash
# Create your first schedule against the dependency-free Scheduler engine.
#
# No npm install, no Firebase, no database — just Node 20+ and curl. This starts
# the engine HTTP server (packages/core), creates a schedule, lists it, and shuts
# the server back down. The whole thing runs in a few seconds from a clean clone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-4180}"
BASE="http://127.0.0.1:${PORT}"

# The standalone engine authorizes from request headers (the services/api Go
# backend is what verifies real Firebase tokens). Any bearer works for the demo.
HEADERS=(
  -H "authorization: Bearer demo-token"
  -H "x-tenant-id: acme"
  -H "x-user-id: u1"
  -H "x-user-role: manager"
  -H "x-correlation-id: demo-1"
  -H "content-type: application/json"
)

echo "▶ Starting the Scheduler engine on ${BASE} (store: memory) ..."
PORT="${PORT}" node "${ROOT}/packages/core/src/server.mjs" &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

# Wait for it to accept connections.
until curl -fsS -o /dev/null "${BASE}/v1/tenants/acme/healthz" "${HEADERS[@]}" 2>/dev/null; do
  sleep 0.2
done

echo
echo "▶ Creating a schedule ..."
curl -fsS -X POST "${BASE}/v1/tenants/acme/schedules" "${HEADERS[@]}" -d '{"name":"Week 1"}'
echo
echo
echo "▶ Listing schedules ..."
curl -fsS "${BASE}/v1/tenants/acme/schedules" "${HEADERS[@]}"
echo
echo
echo "✅ You just created and read a schedule against your own self-hosted engine."
echo "   Next: run the full Go API (services/api) and the web app (apps/web) — see the README."
