#!/usr/bin/env bash
# Seed a VERIFIED user in the Firebase Auth emulator (idempotent) so the login→home
# e2e can reach home (login gates on email verification, parity with Flutter).
# Recipe that works on the emulator: create/find the user, then admin-set emailVerified
# via accounts:update with `Authorization: Bearer owner` (the oobCode flow is unreliable here).
#   bash seed.sh [email] [password]
set -uo pipefail
EMU=http://127.0.0.1:9099/identitytoolkit.googleapis.com/v1
KEY=AIzaSyDpLc-placeholder-ci-key-not-real        # app's (placeholder) key; emulator is singleProjectMode
EMAIL=${1:-qa-verified@example.com}; PW=${2:-Password123!}

get_localid(){ curl -s -X POST "$EMU/accounts:$1?key=$KEY" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\",\"returnSecureToken\":true}" \
  | sed -n 's/.*"localId":"\([^"]*\)".*/\1/p'; }

localId="$(get_localid signInWithPassword)"
[ -z "$localId" ] && localId="$(get_localid signUp)"
[ -z "$localId" ] && { echo "seed: FAILED to create/find $EMAIL"; exit 1; }

curl -s -X POST "$EMU/accounts:update" -H 'Authorization: Bearer owner' \
  -H 'Content-Type: application/json' -d "{\"localId\":\"$localId\",\"emailVerified\":true}" >/dev/null

# Logged-in pages: the API derives tenant/role from token CLAIMS (IDOR-remediation), so the
# user needs tenant_id + role custom claims (tenant_id = own uid, the app's tenant convention).
curl -s -X POST "$EMU/accounts:update" -H 'Authorization: Bearer owner' -H 'Content-Type: application/json' \
  -d "{\"localId\":\"$localId\",\"customAttributes\":\"{\\\"tenant_id\\\":\\\"$localId\\\",\\\"role\\\":\\\"manager\\\"}\"}" >/dev/null

idt="$(curl -s -X POST "$EMU/accounts:signInWithPassword?key=$KEY" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PW\",\"returnSecureToken\":true}" | sed -n 's/.*"idToken":"\([^"]*\)".*/\1/p')"
if curl -s -X POST "$EMU/accounts:lookup?key=$KEY" -H 'Content-Type: application/json' \
     -d "{\"idToken\":\"$idt\"}" | grep -q '"emailVerified":true'; then
  echo "seed: $EMAIL verified ✓ (tenant_id+role claims set)"
else
  echo "seed: verify FAILED for $EMAIL"; exit 1
fi

# Data pages: if the Go API is up, ensure a schedule exists for this tenant (uid) so the
# my-schedules e2e has data to render. No-op if the API isn't running.
API=${SCHEDULER_API:-http://127.0.0.1:4180}
if curl -s -m 3 -o /dev/null "$API" 2>/dev/null || curl -s -m 3 -o /dev/null "$API/healthz" 2>/dev/null; then
  has=$(curl -s -H "Authorization: Bearer $idt" -H "X-Correlation-Id: seed" "$API/v1/tenants/$localId/schedules" 2>/dev/null | grep -o 'QA Demo Schedule')
  if [ -z "$has" ]; then
    curl -s -X POST -H "Authorization: Bearer $idt" -H "X-Correlation-Id: seed" -H 'Content-Type: application/json' \
      -d '{"name":"QA Demo Schedule","status":"active"}' "$API/v1/tenants/$localId/schedules" >/dev/null
    echo "seed: created QA Demo Schedule"
  else
    echo "seed: QA Demo Schedule present"
  fi
else
  echo "seed: (Go API not up — schedule data pages will be empty)"
fi
