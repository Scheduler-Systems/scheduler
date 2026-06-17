package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Date

class CalculateUserAttendanceTest {

    @Test
    fun `should calculate employer attendance for week period`() {
        val input = CalculateUserAttendanceInput(
            scheduleId = "s-1",
            userId = "user-1",
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = listOf("Alice", "Bob", "", "Charlie", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "")
                )
            ),
            role = UserRole.EMPLOYER,
            employeeName = "Employer"
        )

        val result = calculateUserAttendance(input)
        assertEquals("3/21", result)
    }

    @Test
    fun `should calculate employee attendance with their name`() {
        val input = CalculateUserAttendanceInput(
            scheduleId = "s-1",
            userId = "emp-1",
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, false),
            builtSchedules = listOf(
                BuiltSchedule(
                    schedule = emptyList(),
                    firstWeekdayDatetime = Date(),
                    lastWeekdayDatetime = Date(),
                    currentPriorities = listOf("Alice", "Bob,Alice", "", "", "", "", "", "", "", "", "", "", "", "")
                )
            ),
            role = UserRole.EMPLOYEE,
            employeeName = "Alice"
        )

        val result = calculateUserAttendance(input)
        assertEquals("2/14", result)
    }

    @Test
    fun `should handle empty built schedules`() {
        val input = CalculateUserAttendanceInput(
            scheduleId = "s-1",
            userId = "emp-1",
            period = Period.WEEK,
            enabledShifts = EnabledShifts(true, true, true),
            builtSchedules = emptyList(),
            role = UserRole.EMPLOYEE,
            employeeName = "Alice"
        )

        val result = calculateUserAttendance(input)
        assertEquals("0/21", result)
    }
}
