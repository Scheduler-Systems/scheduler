#!/usr/bin/env bash
# Run the whole Scheduler stack locally with ZERO external accounts:
# Firebase emulators (auth + firestore) + Go API + Next.js web, all wired to a
# `demo-` project id (which Firebase treats as emulator-only — no real project).
#
# Requirements: Node 20+, Go 1.22+, a JDK (11+), and the Firebase CLI.
# Usage: ./scripts/dev.sh   (or: make dev)   — Ctrl+C stops everything.
# Ports are overridable if something is already bound, e.g.:
#   FS_PORT=8097 AUTH_PORT=9097 ./scripts/dev.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ID="${SCHEDULER_DEMO_PROJECT:-demo-scheduler}"   # `demo-` prefix => emulator-only, no real Firebase project
AUTH_PORT="${AUTH_PORT:-9099}"
FS_PORT="${FS_PORT:-8088}"
UI_PORT="${UI_PORT:-4001}"
API_PORT="${API_PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"

# Point BOTH the Go API and the web's Admin SDK at the local emulators.
export FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:${AUTH_PORT}"
export FIRESTORE_EMULATOR_HOST="127.0.0.1:${FS_PORT}"

command -v firebase >/dev/null || { echo "✗ Firebase CLI not found — install: npm i -g firebase-tools"; exit 1; }
command -v go >/dev/null || { echo "✗ Go not found (need 1.22+)"; exit 1; }
command -v node >/dev/null || { echo "✗ Node not found (need 20+)"; exit 1; }

# Build an emulator config with the chosen ports (defaults come from firebase.json).
EMU_CONFIG="$(mktemp -t scheduler-emu-XXXX.json)"
node -e '
  const fs=require("fs"), p=process.argv;
  const c=JSON.parse(fs.readFileSync(p[1],"utf8"));
  c.emulators=c.emulators||{};
  c.emulators.auth={port:+p[2]}; c.emulators.firestore={port:+p[3]};
  c.emulators.ui={enabled:true,port:+p[4]}; c.emulators.singleProjectMode=true;
  delete c.functions; delete c.hosting; // open core ships no functions emulator source
  fs.writeFileSync(p[5], JSON.stringify(c,null,2));
' "$ROOT/apps/web/firebase.json" "$AUTH_PORT" "$FS_PORT" "$UI_PORT" "$EMU_CONFIG"

pids=()
cleanup() { echo; echo "▶ stopping..."; for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -f "$EMU_CONFIG"; }
trap cleanup EXIT INT TERM

echo "▶ [1/4] Firebase emulators (auth :$AUTH_PORT, firestore :$FS_PORT, ui :$UI_PORT) — project '$PROJECT_ID'"
( cd "$ROOT/apps/web" && firebase emulators:start --only auth,firestore --project "$PROJECT_ID" --config "$EMU_CONFIG" ) &
pids+=($!)

echo "▶ waiting for emulators..."
until curl -fsS -o /dev/null "http://127.0.0.1:${FS_PORT}/" 2>/dev/null; do sleep 0.5; done
until curl -fsS -o /dev/null "http://127.0.0.1:${AUTH_PORT}/" 2>/dev/null; do sleep 0.5; done

echo "▶ [2/4] Seeding a test user (zero external accounts)"
"$ROOT/scripts/seed-dev.sh" "$PROJECT_ID" "$AUTH_PORT" || echo "  (seed skipped/failed — non-fatal)"

echo "▶ [3/4] Go API on :$API_PORT (SCHEDULER_STORE=firestore → firestore emulator)"
( cd "$ROOT/services/api" && SCHEDULER_STORE=firestore FIREBASE_PROJECT_ID="$PROJECT_ID" PORT="$API_PORT" go run ./cmd/scheduler-api ) &
pids+=($!)

echo "▶ [4/4] Web on :$WEB_PORT (Firebase emulator mode)"
if [ ! -d "$ROOT/apps/web/node_modules" ]; then ( cd "$ROOT/apps/web" && npm install ); fi
( cd "$ROOT/apps/web" \
    && NEXT_PUBLIC_USE_FIREBASE_EMULATORS=true \
       NEXT_PUBLIC_FIREBASE_API_KEY=demo-emulator-key \
       NEXT_PUBLIC_FIREBASE_PROJECT_ID="$PROJECT_ID" \
       NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN="${PROJECT_ID}.firebaseapp.com" \
       NEXT_PUBLIC_FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:${AUTH_PORT}" \
       NEXT_PUBLIC_FIRESTORE_EMULATOR_HOST="127.0.0.1:${FS_PORT}" \
       PORT="$WEB_PORT" npm run dev ) &
pids+=($!)

cat <<EOF

============================================================
  Scheduler is running locally — no external accounts.
    Web app ........ http://localhost:${WEB_PORT}
    Go API ......... http://localhost:${API_PORT}
    Emulator UI .... http://localhost:${UI_PORT}
    Test login ..... owner@demo.test / password123
  Ctrl+C to stop everything.
============================================================
EOF

wait
