package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Date

class FindAllFreeTimesTest {

    @Test
    fun `should return all 21 slots free when no schedules`() {
        val result = findAllFreeTimes(
            FreeTimeInput(
                enabledShifts = EnabledShifts(),
                builtSchedules = emptyList()
            )
        )
        assertEquals(21, result.size)
    }

    @Test
    fun `should return all slots free when schedule has empty stringList`() {
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = listOf(mapOf("stringList" to (0 until 21).map { "" })),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = emptyList()
            )
        )
        val result = findAllFreeTimes(
            FreeTimeInput(
                enabledShifts = EnabledShifts(),
                builtSchedules = builtSchedules
            )
        )
        assertEquals(21, result.size)
    }

    @Test
    fun `should exclude assigned slots`() {
        val stringList = (0 until 21).map { if (it == 0) "Alice" else "" }
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = listOf(mapOf("stringList" to stringList)),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = emptyList()
            )
        )
        val result = findAllFreeTimes(
            FreeTimeInput(
                enabledShifts = EnabledShifts(),
                builtSchedules = builtSchedules
            )
        )
        assertEquals(20, result.size)
        assertTrue(result.none { it.startsWith("Sunday,") && it.contains("07:00 - 15:00") })
    }

    @Test
    fun `should respect disabled shift types`() {
        val input = FreeTimeInput(
            enabledShifts = EnabledShifts(morning = false, afternoon = true, night = false),
            builtSchedules = emptyList()
        )
        val result = findAllFreeTimes(input)
        assertEquals(7, result.size)
        result.forEach { assertTrue(it.contains("15:00 - 23:00")) }
    }

    @Test
    fun `should exclude slots from multiple schedules`() {
        val stringList1 = (0 until 21).map { if (it == 0) "Alice" else "" }
        val stringList2 = (0 until 21).map { if (it == 1) "Bob" else "" }
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = listOf(mapOf("stringList" to stringList1)),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = emptyList()
            ),
            BuiltSchedule(
                schedule = listOf(mapOf("stringList" to stringList2)),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = emptyList()
            )
        )
        val result = findAllFreeTimes(
            FreeTimeInput(
                enabledShifts = EnabledShifts(),
                builtSchedules = builtSchedules
            )
        )
        assertEquals(19, result.size)
    }

    @Test
    fun `should return distinct results`() {
        val stringList = (0 until 21).map { if (it == 0) "Alice" else "" }
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = listOf(mapOf("stringList" to stringList)),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = emptyList()
            )
        )
        val result = findAllFreeTimes(
            FreeTimeInput(
                enabledShifts = EnabledShifts(),
                builtSchedules = builtSchedules
            )
        )
        assertEquals(result.size, result.distinct().size)
    }
}
