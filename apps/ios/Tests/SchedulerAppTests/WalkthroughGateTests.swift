import XCTest
@testable import SchedulerApp

/// The first-time walkthrough must be (a) forceable for e2e, (b) HIDDEN in the emulator/eval
/// build unless forced (so the logged-in flows that reach Home don't regress), and (c) shown on
/// a real first visit. Mirrors Android WalkthroughGateTest + the onboarding gate.
final class WalkthroughGateTests: XCTestCase {

    func testWalkthroughForcedAlwaysShows() {
        XCTAssertTrue(WalkthroughGate.shouldShow(force: true, isEmulator: true, seen: true))
    }

    func testWalkthroughEmulatorNotForcedHidden() {
        XCTAssertFalse(WalkthroughGate.shouldShow(force: false, isEmulator: true, seen: false))
    }

    func testWalkthroughFirstVisitShows() {
        XCTAssertTrue(WalkthroughGate.shouldShow(force: false, isEmulator: false, seen: false))
    }

    func testWalkthroughAfterSeenHidden() {
        XCTAssertFalse(WalkthroughGate.shouldShow(force: false, isEmulator: false, seen: true))
    }
}
