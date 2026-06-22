#!/usr/bin/env bash
# ============================================================================
# Reliable COMBINED consolidation eval on a RAM-constrained host.
#
# The single-pass run.sh keeps both the iOS sim AND the Android emulator booted,
# which exhausts RAM past ~12 areas → rotating app-cold-start flakes. This wrapper
# runs the two platforms as SEPARATE passes with ONLY ONE device booted at a time:
#   PASS 1 — iOS    (Android emulator shut down)          → run.sh --ios
#   PASS 2 — Android (iOS sim shut down, emulator cold-booted) → run.sh --android
# run.sh --android preserves the iOS cache from PASS 1, so PASS 2's scorecard is the
# COMBINED E1. Device switching is a deliberate cold boot between passes (NOT a
# fragile mid-eval snapshot reboot — that was tried and reverted).
#
#   bash run-split.sh            # reliable combined scorecard
# ============================================================================
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${ANDROID_HOME:=$HOME/Library/Android/sdk}"; export ANDROID_HOME
ADB="$ANDROID_HOME/platform-tools/adb"
EMU_BIN="$ANDROID_HOME/emulator/emulator"
AVD="${EVAL_AVD:-Medium_Phone_API_34}"
APK="$HERE/../../apps/android/app/build/outputs/apk/debug/app-debug.apk"

shut_android(){ "$ADB" devices 2>/dev/null | grep -q emulator && { "$ADB" emu kill >/dev/null 2>&1; sleep 5; echo "  (android emulator shut down)"; }; }
shut_ios(){ xcrun simctl shutdown booted >/dev/null 2>&1; sleep 3; echo "  (iOS sims shut down)"; }
cold_boot_android(){
  echo "  (cold-booting android emulator $AVD …)"
  nohup "$EMU_BIN" -avd "$AVD" -no-snapshot-load -no-boot-anim >/tmp/eval-emu-boot.log 2>&1 &
  "$ADB" wait-for-device >/dev/null 2>&1
  local i=0; while [ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ] && [ $i -lt 120 ]; do sleep 2; i=$((i+1)); done
  [ -f "$APK" ] && "$ADB" install -r "$APK" >/dev/null 2>&1 && echo "  (apk reinstalled)"
  echo "  (android ready after ${i} ticks)"
}

echo "════════ PASS 1/2: iOS (Android emulator down) ════════"
shut_android
bash "$HERE/run.sh" --ios

echo
echo "════════ PASS 2/2: Android (iOS sim down) ════════"
shut_ios
cold_boot_android
bash "$HERE/run.sh" --android   # ← preserves iOS cache from PASS 1; prints COMBINED scorecard
