package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Date

class FindBusiestDaysTest {

    @Test
    fun `should return empty for empty built schedules`() {
        val result = findBusiestDays(BusiestDaysInput(emptyList()))
        assertTrue(result.isEmpty())
    }

    @Test
    fun `should return busiest day when only one day has assignments`() {
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = emptyList(),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = listOf(
                    "Alice,Bob", "", "",
                    "Alice", "", "",
                    "", "", ""
                )
            )
        )
        val result = findBusiestDays(BusiestDaysInput(builtSchedules))
        assertEquals(listOf("Sunday"), result)
    }

    @Test
    fun `should return empty list when all priorities empty`() {
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = emptyList(),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = (0 until 21).map { "" }
            )
        )
        val result = findBusiestDays(BusiestDaysInput(builtSchedules))
        assertTrue(result.isEmpty())
    }

    @Test
    fun `should handle multiple schedules with overlapping days`() {
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = emptyList(),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = listOf(
                    "A,B,C", "", "", "D", "", "",
                    "", "", "", "", "", "",
                    "", "", "", "", "", "",
                    "", "", ""
                )
            ),
            BuiltSchedule(
                schedule = emptyList(),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = listOf(
                    "E,F", "", "", "G", "", "",
                    "", "", "", "", "", "",
                    "", "", "", "", "", "",
                    "", "", ""
                )
            )
        )
        val result = findBusiestDays(BusiestDaysInput(builtSchedules))
        assertEquals(listOf("Sunday"), result)
    }

    @Test
    fun `should return all days when tie`() {
        val builtSchedules = listOf(
            BuiltSchedule(
                schedule = emptyList(),
                firstWeekdayDatetime = Date(),
                lastWeekdayDatetime = Date(),
                currentPriorities = listOf(
                    "A", "", "",
                    "B", "", "",
                    "C", "", "",
                    "D", "", "",
                    "E", "", "",
                    "F", "", "",
                    "G", "", ""
                )
            )
        )
        val result = findBusiestDays(BusiestDaysInput(builtSchedules))
        assertEquals(7, result.size)
    }
}
