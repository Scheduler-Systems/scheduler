package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Calendar
import java.util.Date

class IsDeadlinePassedTest {

    @Test
    fun `should return false for invalid weekday`() {
        val now = Date()
        assertFalse(isDeadlinePassed("InvalidDay", "12:00", now))
    }

    @Test
    fun `should return false for invalid time format`() {
        val now = Date()
        assertFalse(isDeadlinePassed("Monday", "invalid", now))
    }

    @Test
    fun `should return false for non-numeric hour`() {
        val now = Date()
        assertFalse(isDeadlinePassed("Monday", "abc:30", now))
    }

    @Test
    fun `should return true when past deadline same day`() {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 14)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)

        val dayNames = listOf("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
        val currentDay = dayNames[cal.get(Calendar.DAY_OF_WEEK) - 1]

        assertTrue(isDeadlinePassed(currentDay, "12:00", cal.time))
    }

    @Test
    fun `should return false when before deadline same day`() {
        val cal = Calendar.getInstance()
        cal.set(Calendar.HOUR_OF_DAY, 10)
        cal.set(Calendar.MINUTE, 0)
        cal.set(Calendar.SECOND, 0)
        cal.set(Calendar.MILLISECOND, 0)

        val dayNames = listOf("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")
        val currentDay = dayNames[cal.get(Calendar.DAY_OF_WEEK) - 1]

        assertFalse(isDeadlinePassed(currentDay, "12:00", cal.time))
    }

    @Test
    fun `should return true when deadline weekday is earlier in week than current`() {
        assertTrue(isDeadlinePassed("Sunday", "12:00", createDate(2026, Calendar.MAY, 11, 10, 0)))
    }

    @Test
    fun `should return false when deadline weekday is later in week`() {
        assertFalse(isDeadlinePassed("Saturday", "12:00", createDate(2026, Calendar.MAY, 11, 10, 0)))
    }

    private fun createDate(year: Int, month: Int, day: Int, hour: Int, minute: Int): Date {
        val cal = Calendar.getInstance()
        cal.set(year, month, day, hour, minute, 0)
        cal.set(Calendar.MILLISECOND, 0)
        return cal.time
    }
}
