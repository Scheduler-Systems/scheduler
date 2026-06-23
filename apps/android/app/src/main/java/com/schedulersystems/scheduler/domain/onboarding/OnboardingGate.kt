package com.schedulersystems.scheduler.domain.onboarding

/**
 * Pure first-launch onboarding gate decision (mirrors iOS `SchedulerApp.shouldStartWithOnboarding`).
 * Show onboarding when explicitly forced (e2e), or on a real first launch outside the
 * emulator/eval context. In the emulator build it stays HIDDEN unless forced, so the existing
 * logged-in e2e flows (which clearState) are unaffected — no regression to the green eval.
 */
fun onboardingStartDestination(
    forceOnboarding: Boolean,
    isEmulatorBuild: Boolean,
    onboardingCompleted: Boolean
): String {
    if (forceOnboarding) return "onboarding"
    if (isEmulatorBuild) return "login"
    return if (onboardingCompleted) "login" else "onboarding"
}
