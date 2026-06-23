package com.schedulersystems.scheduler.domain.walkthrough

/**
 * One-time "first time here" walkthrough gate (the FlutterFlow first_time_employer/employee
 * coach-mark, ported as a native welcome overlay on Home). Same eval-safe shape as the onboarding
 * gate: show when forced (e2e), or on a real first visit outside the emulator build. HIDDEN in the
 * emulator build unless forced, so the existing logged-in e2e flows that reach Home don't regress.
 */
fun shouldShowWalkthrough(
    forceWalkthrough: Boolean,
    isEmulatorBuild: Boolean,
    seen: Boolean
): Boolean {
    if (forceWalkthrough) return true
    if (isEmulatorBuild) return false
    return !seen
}
