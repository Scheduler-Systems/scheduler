package com.schedulersystems.scheduler.domain.revenuecat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SubscriptionTierTest {

    @Test
    fun `FREE has correct properties`() {
        assertEquals("Free", SubscriptionTier.FREE.displayName)
        assertEquals(1, SubscriptionTier.FREE.stations)
        assertEquals(3, SubscriptionTier.FREE.employees)
        assertEquals("$0", SubscriptionTier.FREE.priceMonthly)
        assertEquals("$0", SubscriptionTier.FREE.priceYearly)
        assertFalse(SubscriptionTier.FREE.isUnlimited())
        assertEquals(4, SubscriptionTier.FREE.features.size)
    }

    @Test
    fun `ESSENTIALS has correct properties`() {
        assertEquals("Essentials", SubscriptionTier.ESSENTIALS.displayName)
        assertEquals(3, SubscriptionTier.ESSENTIALS.stations)
        assertEquals(10, SubscriptionTier.ESSENTIALS.employees)
        assertEquals("$9.99", SubscriptionTier.ESSENTIALS.priceMonthly)
        assertEquals("$99.99", SubscriptionTier.ESSENTIALS.priceYearly)
        assertFalse(SubscriptionTier.ESSENTIALS.isUnlimited())
        assertEquals(6, SubscriptionTier.ESSENTIALS.features.size)
    }

    @Test
    fun `PRO has correct properties`() {
        assertEquals("Pro", SubscriptionTier.PRO.displayName)
        assertEquals(5, SubscriptionTier.PRO.stations)
        assertEquals(20, SubscriptionTier.PRO.employees)
        assertEquals("$19.99", SubscriptionTier.PRO.priceMonthly)
        assertEquals("$199.99", SubscriptionTier.PRO.priceYearly)
        assertFalse(SubscriptionTier.PRO.isUnlimited())
        assertEquals(8, SubscriptionTier.PRO.features.size)
    }

    @Test
    fun `ENTERPRISE has correct properties`() {
        assertEquals("Enterprise", SubscriptionTier.ENTERPRISE.displayName)
        assertEquals(Int.MAX_VALUE, SubscriptionTier.ENTERPRISE.stations)
        assertEquals(Int.MAX_VALUE, SubscriptionTier.ENTERPRISE.employees)
        assertEquals("Custom", SubscriptionTier.ENTERPRISE.priceMonthly)
        assertEquals("Custom", SubscriptionTier.ENTERPRISE.priceYearly)
        assertTrue(SubscriptionTier.ENTERPRISE.isUnlimited())
        assertEquals(6, SubscriptionTier.ENTERPRISE.features.size)
    }

    @Test
    fun `TierConfig defaults to tier values`() {
        val config = TierConfig(tier = SubscriptionTier.ESSENTIALS)
        assertEquals(SubscriptionTier.ESSENTIALS, config.tier)
        assertEquals(3, config.stations)
        assertEquals(10, config.employees)
        assertEquals("$9.99", config.priceMonthly)
        assertEquals("$99.99", config.priceYearly)
        assertEquals(6, config.features.size)
    }

    @Test
    fun `TierConfig allows overrides`() {
        val config = TierConfig(
            tier = SubscriptionTier.PRO,
            stations = 10,
            employees = 50,
            priceMonthly = "$29.99",
            priceYearly = "$299.99",
            features = listOf("Custom Feature")
        )
        assertEquals(10, config.stations)
        assertEquals(50, config.employees)
        assertEquals("$29.99", config.priceMonthly)
        assertEquals("$299.99", config.priceYearly)
        assertEquals(listOf("Custom Feature"), config.features)
    }

    @Test
    fun `all tiers have non-empty features`() {
        SubscriptionTier.entries.forEach {
            assertTrue("${it.displayName} should have features", it.features.isNotEmpty())
        }
    }

    @Test
    fun `valueOf returns correct tier`() {
        assertEquals(SubscriptionTier.FREE, SubscriptionTier.valueOf("FREE"))
        assertEquals(SubscriptionTier.PRO, SubscriptionTier.valueOf("PRO"))
    }
}
