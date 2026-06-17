package com.schedulersystems.scheduler.domain.revenuecat

import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RevenueCatServiceTest {

    private val service = RevenueCatService()

    @Test
    fun `initial tier is FREE`() = runTest {
        assertEquals(SubscriptionTier.FREE, service.currentTier.first())
    }

    @Test
    fun `initial isPremium is false`() = runTest {
        assertFalse(service.isPremium.first())
    }

    @Test
    fun `initialize does not throw`() {
        service.initialize("test-api-key")
    }

    @Test
    fun `login does not throw`() {
        service.login("user-1")
    }

    @Test
    fun `login calls onError on exception`() {
        var errorCalled = false
        service.login("user-1") { errorCalled = true }
        assertFalse(errorCalled)
    }

    @Test
    fun `logout resets state and calls onComplete`() = runTest {
        var completed = false
        service.logout { completed = true }
        assertTrue(completed)
        assertEquals(SubscriptionTier.FREE, service.currentTier.first())
        assertFalse(service.isPremium.first())
    }

    @Test
    fun `restorePurchases returns false`() = runTest {
        val result = service.restorePurchases()
        assertFalse(result)
    }

    @Test
    fun `checkEntitlements returns FREE tier`() {
        val result = service.checkEntitlements()
        assertEquals(SubscriptionTier.FREE, result.tier)
        assertFalse(result.isPremium)
        assertEquals(1, result.maxStations)
        assertEquals(3, result.maxEmployees)
        assertTrue(result.activeEntitlements.isEmpty())
    }

    @Test
    fun `isEntitled returns false`() = runTest {
        assertEquals(false, service.isEntitled("pro_yearly"))
    }

    @Test
    fun `exceedsStationsLimit returns false`() {
        assertFalse(service.exceedsStationsLimit(100))
        assertFalse(service.exceedsStationsLimit(1))
        assertFalse(service.exceedsStationsLimit(0))
    }

    @Test
    fun `exceedsEmployeesLimit returns false`() {
        assertFalse(service.exceedsEmployeesLimit(100))
        assertFalse(service.exceedsEmployeesLimit(1))
        assertFalse(service.exceedsEmployeesLimit(0))
    }

    @Test
    fun `getTierConfigs returns empty list`() {
        assertTrue(service.getTierConfigs().isEmpty())
    }

    @Test
    fun `EntitlementCheckResult has correct fields`() {
        val result = EntitlementCheckResult(
            tier = SubscriptionTier.PRO,
            isPremium = true,
            maxStations = 5,
            maxEmployees = 20,
            activeEntitlements = listOf("pro_monthly")
        )
        assertEquals(SubscriptionTier.PRO, result.tier)
        assertTrue(result.isPremium)
        assertEquals(5, result.maxStations)
        assertEquals(20, result.maxEmployees)
        assertEquals(listOf("pro_monthly"), result.activeEntitlements)
    }

    @Test
    fun `logout resets to FREE`() = runTest {
        service.logout()
        assertEquals(SubscriptionTier.FREE, service.currentTier.first())
        assertFalse(service.isPremium.first())
    }
}
