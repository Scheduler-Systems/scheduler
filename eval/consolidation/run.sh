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
A_RESULTS="$ANDROID/app/build/test-results/testDebugUnitTest"
IOS_LOG=/tmp/eval-ios-unit.log
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
: "${JAVA_HOME:=/Library/Java/JavaVirtualMachines/openjdk-21.jdk/Contents/Home}"
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"; export JAVA_HOME ANDROID_HOME

# id | a_unit(class) | a_e2e(flow) | i_unit(iOS test-method substr) | i_e2e(flow) | w_e2e(spec) | verdict
AREAS=(
"auth-email-login|-|-|testSignInWithEmail|-|-|keep-native"
"auth-phone-signin|-|-|testBeginPhoneAuth|-|-|keep-native"
"home|-|-|testHomeViewModel|-|-|keep-native"
"auth-password-reset|AuthViewModelPasswordResetTest|password-reset.yaml|testSendPasswordReset|-|-|done(android); ios e2e pending"
"auth-create-account|AuthViewModelSignUpTest|create-account.yaml|testCreateAccount|-|-|done(android); ios e2e pending"
"auth-verify-email|-|-|-|-|-|todo"
"auth-get-name|-|-|-|-|-|todo(needs-signoff)"
"auth-choose-role|-|-|-|-|-|todo(needs-signoff)"
"onboarding|-|-|testOnboarding|-|-|todo"
"my-schedules|-|-|-|-|-|todo"
"schedule-dashboard|-|-|-|-|-|todo(merge)"
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
echo "▶ Android unit suite…"; ( cd "$ANDROID" && ./gradlew :app:testDebugUnitTest --console=plain >/tmp/eval-a-unit.log 2>&1 ) \
  && echo "  android unit: GREEN" || echo "  android unit: RED (/tmp/eval-a-unit.log)"
if [ $QUICK -eq 0 ]; then
  echo "▶ iOS unit suite (xcodebuild — slow)…"
  ( cd "$IOS" && xcodegen generate >/dev/null 2>&1 && xcodebuild test -project SchedulerApp.xcodeproj \
      -scheme SchedulerApp -destination 'platform=iOS Simulator,name=iPhone 17' >"$IOS_LOG" 2>&1 ) \
    && echo "  ios unit: GREEN" || echo "  ios unit: RED (/tmp/eval-ios-unit.log)"
fi

a_unit_pass(){ [ "$1" = "-" ] && return 1; ls "$A_RESULTS"/*"$1"*.xml >/dev/null 2>&1 \
  && ! grep -lE 'failures="[1-9]|errors="[1-9]' "$A_RESULTS"/*"$1"*.xml >/dev/null 2>&1; }
i_unit_pass(){ [ "$1" = "-" ] && return 1; [ -f "$IOS_LOG" ] || return 1
  grep -qE "Test Case .*'?-?\[?SchedulerAppTests.*$1.* passed" "$IOS_LOG" 2>/dev/null \
  && ! grep -qE "$1.* failed" "$IOS_LOG" 2>/dev/null; }
a_e2e_pass(){ [ "$1" = "-" ] && return 1; [ -f "$MAESTRO_DIR/$1" ] || return 1; [ $QUICK -eq 1 ] && return 1
  ( cd "$ANDROID" && maestro test ".maestro/$1" >/tmp/eval-ae2e-"$1".log 2>&1 ); }

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
  # iOS e2e + web not wired yet → pending unless a flow/spec is defined and passes
  [ "$ie" != "-" ] && IE="❌"   # (no iOS-sim maestro runner yet)
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
echo "  ├ ios-e2e:                     $ie2e/$INSCOPE   (iOS-sim Maestro + Firebase-emulator wiring: TODO)"
echo "  └ web-e2e (feeds E5):          $web/$INSCOPE    (Playwright/make dev: TODO)"
if [ "$e1" -eq "$INSCOPE" ]; then echo "  RESULT: ✅ PASS — consolidation done"; exit 0
else echo "  RESULT: ❌ FAIL — $((INSCOPE-e1)) areas not yet parity on both platforms"; exit 1; fi
