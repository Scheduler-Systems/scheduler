#!/usr/bin/env bash
# ============================================================================
# THE Flutter→native consolidation eval.  *The goal IS this eval.*
# Done = this script reports PASS (every in-scope area green on E1/E2/E3).
# Re-runnable → catches regression. Android-first (the active platform);
# iOS/web columns are scored as they get ported.
#
#   bash eval/consolidation/run.sh            # full: unit + GUI e2e (needs emulator + auth emulator)
#   bash eval/consolidation/run.sh --no-e2e   # fast: parity + unit only
#
# E2 (unit)  = the area's unit test class runs + passes.
# E3 (e2e)   = the area's Maestro flow runs + passes on the zero-account stack.
# E1 (parity)= the area is real+working on the platform := unit ✓ AND e2e ✓.
# Overall PASS := E1 == <in-scope count> (currently 27).
# ============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ANDROID="$ROOT/apps/android"
MAESTRO_DIR="$ANDROID/.maestro"
TEST_RESULTS="$ANDROID/app/build/test-results/testDebugUnitTest"
RUN_E2E=1; [ "${1:-}" = "--no-e2e" ] && RUN_E2E=0
: "${JAVA_HOME:=/Library/Java/JavaVirtualMachines/openjdk-21.jdk/Contents/Home}"
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"
export JAVA_HOME ANDROID_HOME

# id | unit_test_class (substring, '-' if none yet) | maestro_flow ('-' if none yet) | matrix_verdict
AREAS=(
"auth-email-login|-|-|keep-native"
"auth-phone-signin|-|-|keep-native"
"home|-|-|keep-native"
"auth-password-reset|AuthViewModelPasswordResetTest|password-reset.yaml|done"
"auth-create-account|-|-|todo"
"auth-verify-email|-|-|todo"
"auth-get-name|-|-|todo(needs-signoff)"
"auth-choose-role|-|-|todo(needs-signoff)"
"onboarding|-|-|todo"
"my-schedules|-|-|todo"
"schedule-dashboard|-|-|todo(merge)"
"new-schedule-create|-|-|todo(needs-signoff)"
"schedule-build|-|-|todo(needs-signoff,merge)"
"schedule-settings|-|-|todo(needs-signoff)"
"schedule-requests|-|-|todo(needs-signoff)"
"employees-list|-|-|todo"
"employees-add|-|-|todo(needs-signoff)"
"priorities-submission|-|-|todo(needs-signoff)"
"priorities-current|-|-|todo(needs-signoff)"
"archived-schedules|-|-|todo(needs-signoff)"
"export-shifts|-|-|todo(needs-signoff)"
"share-pdf|-|-|todo"
"chat-threads|-|-|todo(needs-signoff,merge)"
"notifications|-|-|todo(needs-signoff)"
"profile-settings|-|-|todo(needs-signoff,merge)"
"policies|-|-|todo"
"walkthroughs|-|-|todo"
)
INSCOPE=${#AREAS[@]}   # 27 (gemini-ai + billing-revenuecat excluded: ML-boundary / hard-gate)

echo "▶ consolidation eval — $INSCOPE in-scope areas"
echo "▶ running Android unit suite once (E2 source)…"
( cd "$ANDROID" && ./gradlew :app:testDebugUnitTest --console=plain >/tmp/eval-unit.log 2>&1 )
UNIT_RC=$?
[ $UNIT_RC -eq 0 ] && echo "  unit suite: GREEN" || echo "  unit suite: RED (see /tmp/eval-unit.log)"

unit_pass() {  # $1 = test class substring
  [ "$1" = "-" ] && return 1
  ls "$TEST_RESULTS"/*"$1"*.xml >/dev/null 2>&1 || return 1
  ! grep -lE 'failures="[1-9]|errors="[1-9]' "$TEST_RESULTS"/*"$1"*.xml >/dev/null 2>&1
}
e2e_pass() {   # $1 = maestro flow file
  [ "$1" = "-" ] && return 1
  [ -f "$MAESTRO_DIR/$1" ] || return 1
  [ $RUN_E2E -eq 1 ] || return 2   # 2 = skipped
  ( cd "$ANDROID" && maestro test ".maestro/$1" >/tmp/eval-e2e-"$1".log 2>&1 )
}

e1=0; e2=0; e3=0
printf '\n%-24s %-6s %-6s %-6s %s\n' AREA E1 E2 E3 VERDICT
printf '%-24s %-6s %-6s %-6s %s\n' "------------------------" "----" "----" "----" "-------"
for row in "${AREAS[@]}"; do
  IFS='|' read -r id unit flow verdict <<< "$row"
  u="❌"; t="❌"; e="❌"
  unit_pass "$unit" && { t="✅"; e2=$((e2+1)); }
  if [ "$flow" != "-" ]; then
    if [ $RUN_E2E -eq 1 ]; then e2e_pass "$flow" && { e="✅"; e3=$((e3+1)); } || e="❌"
    else e="➖"; fi
  fi
  if [ "$t" = "✅" ] && [ "$e" = "✅" ]; then u="✅"; e1=$((e1+1)); fi
  printf '%-24s %-6s %-6s %-6s %s\n' "$id" "$u" "$t" "$e" "$verdict"
done

echo
echo "════ SCORECARD ════"
echo "  E1 parity (unit✓ AND e2e✓): $e1/$INSCOPE"
echo "  E2 unit:                    $e2/$INSCOPE"
echo "  E3 GUI e2e:                 $e3/$INSCOPE  $([ $RUN_E2E -eq 0 ] && echo '(skipped: --no-e2e)')"
if [ "$e1" -eq "$INSCOPE" ]; then echo "  RESULT: ✅ PASS — consolidation done"; exit 0
else echo "  RESULT: ❌ FAIL — $((INSCOPE-e1)) areas remaining"; exit 1; fi
