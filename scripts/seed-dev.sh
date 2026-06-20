#!/usr/bin/env bash
# Seed a test user into the Firebase AUTH emulator (zero external accounts).
# Idempotent: re-running is harmless (a duplicate signUp just errors, ignored).
set -euo pipefail
PROJECT_ID="${1:-demo-scheduler}"
AUTH_PORT="${2:-9099}"
EMAIL="${SEED_EMAIL:-owner@demo.test}"
PASSWORD="${SEED_PASSWORD:-password123}"

# The Auth emulator accepts any API key.
URL="http://127.0.0.1:${AUTH_PORT}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-emulator-key"
curl -fsS -X POST "$URL" \
  -H 'Content-Type: application/json' \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASSWORD}\",\"returnSecureToken\":true}" \
  >/dev/null 2>&1 && echo "  ✓ test user ready: ${EMAIL} / ${PASSWORD}" \
  || echo "  • test user already exists (or emulator busy): ${EMAIL}"
