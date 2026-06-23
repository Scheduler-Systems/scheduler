import Foundation

/// One-time "first time here" walkthrough gate (the FlutterFlow first_time_employer/employee
/// coach-mark, ported as a native welcome overlay on Home). Mirrors the onboarding gate and the
/// Android WalkthroughGate: show when forced (e2e), or on a real first visit outside the emulator
/// context. HIDDEN in the emulator build unless explicitly forced, so the existing logged-in e2e
/// flows that reach Home are unaffected — no regression to the green eval.
enum WalkthroughGate {
    static let homeSeenKey = "home_walkthrough_seen"

    /// Pure decision (same shape as onboardingStartDestination) — unit-tested.
    static func shouldShow(force: Bool, isEmulator: Bool, seen: Bool) -> Bool {
        if force { return true }
        if isEmulator { return false }
        return !seen
    }

    static func shouldShowHomeWalkthrough() -> Bool {
        let args = ProcessInfo.processInfo.arguments
        let force = args.contains { $0.localizedCaseInsensitiveContains("forceWalkthrough") }
        let emulator = ProcessInfo.processInfo.environment["USE_FIREBASE_EMULATOR"] == "true"
            || UserDefaults.standard.bool(forKey: "useFirebaseEmulator")
            || args.contains { $0.localizedCaseInsensitiveContains("useFirebaseEmulator") }
        let seen = UserDefaults.standard.bool(forKey: homeSeenKey)
        return shouldShow(force: force, isEmulator: emulator, seen: seen)
    }

    static func markHomeSeen() {
        UserDefaults.standard.set(true, forKey: homeSeenKey)
    }
}
