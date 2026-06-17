package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Date

class GetAttendanceTest {

    @Test
    fun `should return null for empty built schedules`() {
        val input = AttendanceInput(
            userId = "user-1",
            scheduleId = "s-1",
            isEmployer = true,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = emptyList()
        )
        assertNull(getAttendance(input))
    }

    @Test
    fun `should return employer attendance percentage when some slots occupied`() {
        val priorities = listOf(
            "Alice", "Bob", "Charlie",
            "Alice", "Bob", "Charlie",
            "Alice", "", ""
        )
        val input = AttendanceInput(
            userId = "user-1",
            scheduleId = "s-1",
            isEmployer = true,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = priorities
                )
            )
        )
        val result = getAttendance(input)
        assertEquals((7.0 / 9.0) * 100.0, result!!, 0.01)
    }

    @Test
    fun `should return employee attendance percentage`() {
        val priorities = listOf(
            "Alice", "Bob,Alice", "",
            "Alice", "", "",
            "Alice", "", ""
        )
        val input = AttendanceInput(
            userId = "emp-1",
            scheduleId = "s-1",
            isEmployer = false,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = priorities
                )
            ),
            employeeName = "Alice"
        )
        val result = getAttendance(input)
        assertEquals((4.0 / 9.0) * 100.0, result!!, 0.01)
    }

    @Test
    fun `should return 0 percent when all priorities are empty`() {
        val priorities = (0 until 9).map { "" }
        val input = AttendanceInput(
            userId = "user-1",
            scheduleId = "s-1",
            isEmployer = true,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = priorities
                )
            )
        )
        assertEquals(0.0, getAttendance(input)!!, 0.01)
    }

    @Test
    fun `should return null when built schedules have empty priority lists`() {
        val input = AttendanceInput(
            userId = "user-1",
            scheduleId = "s-1",
            isEmployer = true,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = emptyList()
                )
            )
        )
        assertNull(getAttendance(input))
    }

    @Test
    fun `should return 100 percent when all slots occupied as manager`() {
        val priorities = listOf("A", "B", "C")
        val input = AttendanceInput(
            userId = "user-1",
            scheduleId = "s-1",
            isEmployer = true,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = priorities
                )
            )
        )
        val result = getAttendance(input)
        assertEquals(100.0, result!!, 0.01)
    }

    @Test
    fun `should return 0 percent when employee not in any slot`() {
        val priorities = listOf("A", "B", "C")
        val input = AttendanceInput(
            userId = "emp-1",
            scheduleId = "s-1",
            isEmployer = false,
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = priorities
                )
            ),
            employeeName = "Alice"
        )
        val result = getAttendance(input)
        assertEquals(0.0, result!!, 0.01)
    }
}
