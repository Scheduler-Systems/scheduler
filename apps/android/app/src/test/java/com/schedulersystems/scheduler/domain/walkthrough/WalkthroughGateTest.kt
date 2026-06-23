package com.schedulersystems.scheduler.domain.walkthrough

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The first-time walkthrough must be (a) forceable for e2e, (b) HIDDEN in the emulator/eval build
 * unless forced (so the logged-in flows that reach Home don't regress), and (c) shown on a real
 * first visit. Mirrors iOS WalkthroughGateTests + the onboarding gate.
 */
class WalkthroughGateTest {

    @Test
    fun forced_alwaysShows() {
        assertTrue(shouldShowWalkthrough(forceWalkthrough = true, isEmulatorBuild = true, seen = true))
    }

    @Test
    fun emulatorBuild_notForced_hidden() {
        assertFalse(shouldShowWalkthrough(forceWalkthrough = false, isEmulatorBuild = true, seen = false))
    }

    @Test
    fun firstVisit_shows() {
        assertTrue(shouldShowWalkthrough(forceWalkthrough = false, isEmulatorBuild = false, seen = false))
    }

    @Test
    fun afterSeen_hidden() {
        assertFalse(shouldShowWalkthrough(forceWalkthrough = false, isEmulatorBuild = false, seen = true))
    }
}
