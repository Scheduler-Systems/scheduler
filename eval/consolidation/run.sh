#!/usr/bin/env bash
# ============================================================================
# THE Flutter→native consolidation eval — PER-PLATFORM (Android + iOS + web).
# *The goal IS this eval.* Re-runnable → catches regression.
#
# E1 (parity)   per area = real+tested on BOTH native platforms:
#               (android_unit ✓ AND android_e2e ✓) AND (ios_unit ✓ AND ios_e2e ✓)
# Sub-scores reported so progress per platform is visible:
#   android-full · ios-unit · ios-e2e · web-e2e (web feeds E5, not E1)
# DONE = E1 == in-scope count (27).
#
#   bash run.sh           # full: android unit + ios unit (xcodebuild) + e2e
#   bash run.sh --quick   # unit attribution only (skip e2e + iOS rebuild)
# ============================================================================
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ANDROID="$ROOT/apps/android"; IOS="$ROOT/apps/ios"
MAESTRO_DIR="$ANDROID/.maestro"
IOS_MAESTRO_DIR="$IOS/.maestro"
A_RESULTS="$ANDROID/app/build/test-results/testDebugUnitTest"
IOS_LOG=/tmp/eval-ios-unit.log
IOS_DD="$IOS/build/dd"                       # iOS derivedData (shared by unit + e2e .app)
IOS_DEST='platform=iOS Simulator,name=iPhone 17'
IOS_UDID=""                                  # resolved/booted below when e2e runs
E2E_CACHE=/tmp/eval-e2e-cache                 # per-run memo of e2e results (run each flow once)
rm -rf "$E2E_CACHE" 2>/dev/null; mkdir -p "$E2E_CACHE"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
: "${JAVA_HOME:=/Library/Java/JavaVirtualMachines/openjdk-21.jdk/Contents/Home}"
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"; export JAVA_HOME ANDROID_HOME

# id | a_unit(class) | a_e2e(flow) | i_unit(iOS test-method substr) | i_e2e(flow) | w_e2e(spec) | verdict
AREAS=(
"auth-email-login|AuthViewModelTest|email-login.yaml|testSignInWithEmail|email-login.yaml|-|done (android+ios, unit+e2e)"
"auth-phone-signin|-|-|testBeginPhoneAuth|-|-|keep-native"
"home|HomeViewModelTest|email-login.yaml|testHomeViewModel|email-login.yaml|-|done (android+ios; login→home content)"
"auth-password-reset|AuthViewModelPasswordResetTest|password-reset.yaml|testSendPasswordReset|password-reset.yaml|-|done (android+ios, unit+e2e)"
"auth-create-account|AuthViewModelSignUpTest|create-account.yaml|testCreateAccount|create-account.yaml|-|done (android+ios, unit+e2e)"
"auth-verify-email|AuthViewModelVerifyEmailTest|verify-email.yaml|testVerifyEmail|verify-email.yaml|-|done (android+ios, unit+e2e)"
"auth-get-name|-|-|-|-|-|todo(needs-signoff)"
"auth-choose-role|-|-|-|-|-|todo(needs-signoff)"
"onboarding|-|-|testOnboarding|-|-|todo"
"my-schedules|ScheduleListViewModelTest|my-schedules.yaml|testHomeViewModel|my-schedules.yaml|-|done (android+ios; login→Go-API data)"
"schedule-dashboard|ScheduleDetailViewModelTest|schedule-dashboard.yaml|testScheduleDetailView|schedule-dashboard.yaml|-|done (android+ios; login→detail by id)"
"new-schedule-create|-|-|-|-|-|todo(needs-signoff)"
"schedule-build|-|-|-|-|-|todo(needs-signoff,merge)"
"schedule-settings|-|-|-|-|-|todo(needs-signoff)"
"schedule-requests|-|-|-|-|-|todo(needs-signoff)"
"employees-list|-|-|-|-|-|todo"
"employees-add|-|-|-|-|-|todo(needs-signoff)"
"priorities-submission|-|-|-|-|-|todo(needs-signoff)"
"priorities-current|-|-|-|-|-|todo(needs-signoff)"
"archived-schedules|-|-|-|-|-|todo(needs-signoff)"
"export-shifts|-|-|-|-|-|todo(needs-signoff)"
"share-pdf|-|-|-|-|-|todo"
"chat-threads|-|-|-|-|-|todo(needs-signoff,merge)"
"notifications|-|-|-|-|-|todo(needs-signoff)"
"profile-settings|-|-|-|-|-|todo(needs-signoff,merge)"
"policies|-|-|-|-|-|todo"
"walkthroughs|-|-|-|-|-|todo"
)
INSCOPE=${#AREAS[@]}   # 27 (gemini-ai + billing-revenuecat excluded)

echo "▶ consolidation eval — $INSCOPE in-scope areas (per-platform)"
# Resolve the Android emulator serial so Maestro targets it explicitly (an iOS sim may be
# co-booted for iOS e2e — without --device, Maestro can grab the wrong device).
AND_SERIAL="$("$ANDROID_HOME/platform-tools/adb" devices 2>/dev/null | awk '/emulator-|device$/ && $2=="device"{print $1; exit}')"
# Seed a verified user in the Auth emulator so the login→home e2e can reach home (idempotent).
[ $QUICK -eq 0 ] && { echo "▶ seeding verified login user…"; bash "$(dirname "$0")/seed.sh" 2>&1 | sed 's/^/  /'; }
echo "▶ Android unit suite…"; ( cd "$ANDROID" && ./gradlew :app:testDebugUnitTest --console=plain >/tmp/eval-a-unit.log 2>&1 ) \
  && echo "  android unit: GREEN" || echo "  android unit: RED (/tmp/eval-a-unit.log)"
if [ $QUICK -eq 0 ]; then
  echo "▶ iOS unit + e2e setup (xcodebuild — slow)…"
  # iOS e2e precondition: the Firebase Auth emulator must be running on 127.0.0.1:9099.
  # One simulator serves unit + e2e: reuse a booted iPhone, else boot iPhone 17.
  IOS_UDID="$(xcrun simctl list devices booted 2>/dev/null | grep -iE 'iPhone' | grep -oE '[0-9A-F-]{36}' | head -1)"
  if [ -z "$IOS_UDID" ]; then
    IOS_UDID="$(xcrun simctl list devices available 2>/dev/null | grep -E 'iPhone 17 \(' | grep -oE '[0-9A-F-]{36}' | head -1)"
    [ -n "$IOS_UDID" ] && xcrun simctl boot "$IOS_UDID" >/dev/null 2>&1
  fi
  IOS_TEST_DEST="$IOS_DEST"; [ -n "$IOS_UDID" ] && IOS_TEST_DEST="id=$IOS_UDID"
  ( cd "$IOS" && xcodegen generate >/dev/null 2>&1 && xcodebuild test -project SchedulerApp.xcodeproj \
      -scheme SchedulerApp -destination "$IOS_TEST_DEST" -derivedDataPath "$IOS_DD" >"$IOS_LOG" 2>&1 ) \
    && echo "  ios unit: GREEN" || echo "  ios unit: RED ($IOS_LOG)"
  # Install the freshly-built (ad-hoc-signed) .app so iOS Maestro e2e can drive it.
  IOS_APP="$(find "$IOS_DD/Build/Products" -maxdepth 3 -name 'SchedulerApp.app' 2>/dev/null | head -1)"
  [ -n "$IOS_UDID" ] && [ -n "$IOS_APP" ] && xcrun simctl install "$IOS_UDID" "$IOS_APP" >/dev/null 2>&1 \
    && echo "  ios app installed → e2e ready ($IOS_UDID)"
fi

a_unit_pass(){ [ "$1" = "-" ] && return 1; ls "$A_RESULTS"/*"$1"*.xml >/dev/null 2>&1 \
  && ! grep -lE 'failures="[1-9]|errors="[1-9]' "$A_RESULTS"/*"$1"*.xml >/dev/null 2>&1; }
i_unit_pass(){ [ "$1" = "-" ] && return 1; [ -f "$IOS_LOG" ] || return 1
  grep -qE "Test Case .*'?-?\[?SchedulerAppTests.*$1.* passed" "$IOS_LOG" 2>/dev/null \
  && ! grep -qE "$1.* failed" "$IOS_LOG" 2>/dev/null; }
# e2e runners: memoize per flow (a flow shared by two areas runs ONCE) + retry once
# (a cold start after clearState can lose the render race under load; the 2nd attempt is warm).
a_e2e_pass(){ [ "$1" = "-" ] && return 1; [ -f "$MAESTRO_DIR/$1" ] || return 1; [ $QUICK -eq 1 ] && return 1
  local m="$E2E_CACHE/a-$1"; [ -f "$m.pass" ] && return 0; [ -f "$m.fail" ] && return 1
  local rc=1 a; for a in 1 2; do
    ( cd "$ANDROID" && maestro ${AND_SERIAL:+--device "$AND_SERIAL"} test ".maestro/$1" >/tmp/eval-ae2e-"$1".log 2>&1 ) && { rc=0; break; }
  done
  [ $rc -eq 0 ] && touch "$m.pass" || touch "$m.fail"; return $rc; }
i_e2e_pass(){ [ "$1" = "-" ] && return 1; [ -f "$IOS_MAESTRO_DIR/$1" ] || return 1; [ $QUICK -eq 1 ] && return 1
  [ -n "$IOS_UDID" ] || return 1
  local m="$E2E_CACHE/i-$1"; [ -f "$m.pass" ] && return 0; [ -f "$m.fail" ] && return 1
  local rc=1 a; for a in 1 2; do
    ( cd "$IOS" && maestro --device "$IOS_UDID" test ".maestro/$1" >/tmp/eval-ie2e-"$1".log 2>&1 ) && { rc=0; break; }
  done
  [ $rc -eq 0 ] && touch "$m.pass" || touch "$m.fail"; return $rc; }

e1=0; afull=0; iunit=0; ie2e=0; web=0
printf '\n%-22s %-4s | %-7s %-7s | %-7s %-7s | %-5s | %s\n' AREA E1 a-unit a-e2e i-unit i-e2e web VERDICT
printf '%-22s %-4s | %-7s %-7s | %-7s %-7s | %-5s | %s\n' "----------------------" "--" "------" "-----" "------" "-----" "---" "-------"
for row in "${AREAS[@]}"; do
  IFS='|' read -r id au ae iu ie we verdict <<< "$row"
  AU="·"; AE="·"; IU="·"; IE="·"; WE="·"
  a_unit_pass "$au" && AU="✅"
  a_e2e_pass "$ae" && { AE="✅"; }
  [ "$ae" != "-" ] && [ "$AE" != "✅" ] && AE="❌"
  [ "$au" != "-" ] && [ "$AU" != "✅" ] && AU="❌"
  i_unit_pass "$iu" && { IU="✅"; iunit=$((iunit+1)); }
  [ "$iu" != "-" ] && [ "$IU" != "✅" ] && IU="❌"
  i_e2e_pass "$ie" && { IE="✅"; ie2e=$((ie2e+1)); }
  [ "$ie" != "-" ] && [ "$IE" != "✅" ] && IE="❌"
  # web e2e not wired yet → pending unless a spec is defined and passes
  [ "$we" != "-" ] && WE="❌"
  a_full=0; [ "$AU" = "✅" ] && [ "$AE" = "✅" ] && { a_full=1; afull=$((afull+1)); }
  i_full=0; [ "$IU" = "✅" ] && [ "$IE" = "✅" ] && i_full=1
  E="❌"; [ $a_full -eq 1 ] && [ $i_full -eq 1 ] && { E="✅"; e1=$((e1+1)); }
  printf '%-22s %-4s | %-7s %-7s | %-7s %-7s | %-5s | %s\n' "$id" "$E" "$AU" "$AE" "$IU" "$IE" "$WE" "$verdict"
done

echo
echo "════ SCORECARD (per-platform) ════"
echo "  E1 parity (BOTH natives full): $e1/$INSCOPE   ← the done bar"
echo "  ├ android-full (unit+e2e):     $afull/$INSCOPE"
echo "  ├ ios-unit:                    $iunit/$INSCOPE"
echo "  ├ ios-e2e:                     $ie2e/$INSCOPE   (Maestro on iOS sim + Firebase Auth emulator)"
echo "  └ web-e2e (feeds E5):          $web/$INSCOPE    (Playwright/make dev: TODO)"
if [ "$e1" -eq "$INSCOPE" ]; then echo "  RESULT: ✅ PASS — consolidation done"; exit 0
else echo "  RESULT: ❌ FAIL — $((INSCOPE-e1)) areas not yet parity on both platforms"; exit 1; fi
