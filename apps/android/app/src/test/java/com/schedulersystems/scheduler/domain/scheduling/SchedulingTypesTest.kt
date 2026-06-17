package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SchedulingTypesTest {

    @Test
    fun `shiftIndex returns correct values`() {
        assertEquals(0, shiftIndex(ShiftType.MORNING))
        assertEquals(1, shiftIndex(ShiftType.AFTERNOON))
        assertEquals(2, shiftIndex(ShiftType.NIGHT))
    }

    @Test
    fun `slotIndex returns correct values`() {
        assertEquals(0, slotIndex(0, ShiftType.MORNING))
        assertEquals(1, slotIndex(0, ShiftType.AFTERNOON))
        assertEquals(2, slotIndex(0, ShiftType.NIGHT))
        assertEquals(3, slotIndex(1, ShiftType.MORNING))
        assertEquals(6, slotIndex(2, ShiftType.MORNING))
    }

    @Test
    fun `dayIndexFromSlot returns correct values`() {
        assertEquals(0, dayIndexFromSlot(0))
        assertEquals(0, dayIndexFromSlot(2))
        assertEquals(1, dayIndexFromSlot(3))
        assertEquals(2, dayIndexFromSlot(7))
    }

    @Test
    fun `shiftIndexFromSlot returns correct values`() {
        assertEquals(0, shiftIndexFromSlot(0))
        assertEquals(1, shiftIndexFromSlot(1))
        assertEquals(2, shiftIndexFromSlot(2))
        assertEquals(0, shiftIndexFromSlot(3))
    }

    @Test
    fun `gridToArray converts 7x3 grid to 21 element list`() {
        val grid = List(7) { day -> List(3) { shift -> "d${day}s${shift}" } }
        val result = gridToArray(grid)
        assertEquals(21, result.size)
        assertEquals("d0s0", result[0])
        assertEquals("d6s2", result[20])
    }

    @Test
    fun `gridToArray handles nulls`() {
        val grid = List(7) { List(3) { null } }
        val result = gridToArray(grid)
        assertEquals(21, result.size)
        result.forEach { assertEquals("", it) }
    }

    @Test
    fun `enabledShiftCount returns correct totals`() {
        assertEquals(3, enabledShiftCount(EnabledShifts(true, true, true)))
        assertEquals(2, enabledShiftCount(EnabledShifts(true, true, false)))
        assertEquals(1, enabledShiftCount(EnabledShifts(false, false, true)))
        assertEquals(0, enabledShiftCount(EnabledShifts(false, false, false)))
    }

    @Test
    fun `evaluateStationEntitlementSelection free user with 1 station`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 1,
            isPremiumUser = false,
            activeEntitlements = null
        )
        assertTrue(result.allowed)
        assertEquals(1, result.enforcedStationCount)
    }

    @Test
    fun `evaluateStationEntitlementSelection free user with multiple stations blocked`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = false,
            activeEntitlements = null
        )
        assertFalse(result.allowed)
        assertEquals(1, result.enforcedStationCount)
        assertEquals("Premium Required", result.dialogTitle)
    }

    @Test
    fun `evaluateStationEntitlementSelection essentials premium allows up to 3`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = true,
            activeEntitlements = listOf("essentials_monthly")
        )
        assertTrue(result.allowed)
        assertEquals(3, result.enforcedStationCount)
    }

    @Test
    fun `evaluateStationEntitlementSelection pro premium allows up to 5`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 5,
            isPremiumUser = true,
            activeEntitlements = listOf("pro_yearly")
        )
        assertTrue(result.allowed)
        assertEquals(5, result.enforcedStationCount)
    }

    @Test
    fun `evaluateStationEntitlementSelection pro blocked at 6`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 6,
            isPremiumUser = true,
            activeEntitlements = listOf("pro_yearly")
        )
        assertFalse(result.allowed)
    }

    @Test
    fun `evaluateStationEntitlementSelection essentials blocked at 4`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 4,
            isPremiumUser = true,
            activeEntitlements = listOf("essentials_monthly")
        )
        assertFalse(result.allowed)
    }

    @Test
    fun `evaluateStationEntitlementSelection debug bypass`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 10,
            isPremiumUser = false,
            activeEntitlements = null,
            allowLocalDebugBypass = true
        )
        assertTrue(result.allowed)
        assertEquals(10, result.enforcedStationCount)
        assertTrue(result.usedLocalBypass)
    }

    @Test
    fun `evaluateStationEntitlementSelection empty entitlements for premium`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = true,
            activeEntitlements = emptyList()
        )
        assertFalse(result.allowed)
        assertEquals("Subscription Check Failed", result.dialogTitle)
    }

    @Test
    fun `evaluateStationEntitlementSelection pro 5 allowed`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 5,
            isPremiumUser = true,
            activeEntitlements = listOf("pro_monthly")
        )
        assertTrue(result.allowed)
        assertEquals(5, result.enforcedStationCount)
    }

    @Test
    fun `evaluateStationEntitlementSelection essentials employee filtered`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = true,
            activeEntitlements = listOf("essentials_employee_monthly")
        )
        assertFalse(result.allowed)
    }

    @Test
    fun `evaluateStationEntitlementSelection essentials 3 stations`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = true,
            activeEntitlements = listOf("essentials")
        )
        assertTrue(result.allowed)
    }

    @Test
    fun `evaluateStationEntitlementSelection pro 4 stations`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 4,
            isPremiumUser = true,
            activeEntitlements = listOf("pro")
        )
        assertTrue(result.allowed)
    }

    @Test
    fun `evaluateStationEntitlementSelection upgrades message for 2 stations no premium`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 2,
            isPremiumUser = false,
            activeEntitlements = null
        )
        assertFalse(result.allowed)
        assertEquals("Premium Required", result.dialogTitle)
    }

    @Test
    fun `evaluateStationEntitlementSelection upgrades message for 3 stations`() {
        val result = evaluateStationEntitlementSelection(
            selectedStationCount = 3,
            isPremiumUser = true,
            activeEntitlements = listOf("free")
        )
        assertFalse(result.allowed)
        assertEquals("Upgrade Required", result.dialogTitle)
    }

    @Test
    fun `EnabledShifts defaults`() {
        val shifts = EnabledShifts()
        assertTrue(shifts.morning)
        assertTrue(shifts.afternoon)
        assertTrue(shifts.night)
        assertEquals("07:00 - 15:00", shifts.morningShiftTime)
        assertEquals("15:00 - 23:00", shifts.afternoonShiftTime)
        assertEquals("23:00 - 07:00", shifts.nightShiftTime)
    }

    @Test
    fun `StationConfig defaults`() {
        val config = StationConfig(numOfPeople = 2, stationNum = 1)
        assertTrue(config.morning)
        assertTrue(config.afternoon)
        assertTrue(config.night)
        assertEquals(2, config.numOfPeople)
        assertEquals(1, config.stationNum)
    }
}
