package com.schedulersystems.scheduler.domain.onboarding

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * The first-launch gate must (a) be forceable for e2e, (b) stay HIDDEN in the emulator/eval
 * build unless forced (so the 23 logged-in flows that clearState don't regress), and
 * (c) show on a real production first launch. Mirrors iOS shouldStartWithOnboarding.
 */
class OnboardingGateTest {

    @Test
    fun forced_alwaysShowsOnboarding() {
        // forced wins even in the emulator build with a completed flag.
        assertEquals("onboarding", onboardingStartDestination(forceOnboarding = true, isEmulatorBuild = true, onboardingCompleted = true))
    }

    @Test
    fun emulatorBuild_notForced_skipsOnboarding() {
        // The eval context: clearState wipes the flag, but onboarding stays hidden -> no regression.
        assertEquals("login", onboardingStartDestination(forceOnboarding = false, isEmulatorBuild = true, onboardingCompleted = false))
    }

    @Test
    fun productionFirstLaunch_showsOnboarding() {
        assertEquals("onboarding", onboardingStartDestination(forceOnboarding = false, isEmulatorBuild = false, onboardingCompleted = false))
    }

    @Test
    fun productionAfterCompletion_skipsOnboarding() {
        assertEquals("login", onboardingStartDestination(forceOnboarding = false, isEmulatorBuild = false, onboardingCompleted = true))
    }
}
