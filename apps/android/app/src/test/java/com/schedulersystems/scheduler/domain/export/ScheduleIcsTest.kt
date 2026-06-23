package com.schedulersystems.scheduler.domain.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class ScheduleIcsTest {

    private val mondayEpoch = LocalDate.of(2026, 6, 22).toEpochDay() // a real Monday

    @Test
    fun producesValidVCalendarEnvelope() {
        val ics = buildScheduleIcs("QA Demo Schedule", listOf("Morning"), listOf(listOf(listOf("Alex Worker"))), mondayEpoch)
        assertTrue(ics.startsWith("BEGIN:VCALENDAR"))
        assertTrue(ics.contains("VERSION:2.0"))
        assertTrue(ics.trimEnd().endsWith("END:VCALENDAR"))
        assertTrue(ics.contains("X-WR-CALNAME:QA Demo Schedule"))
    }

    @Test
    fun oneVeventPerAssignedWorkerWithRealName() {
        val grid = listOf(
            listOf(listOf("Alex Worker", "Sam")), // day 0, shift 0: two workers
            listOf(listOf("Carol"))               // day 1, shift 0
        )
        val ics = buildScheduleIcs("Roster", listOf("Morning"), grid, mondayEpoch)
        assertEquals(3, Regex("BEGIN:VEVENT").findAll(ics).count())
        assertTrue(ics.contains("SUMMARY:Morning shift — Alex Worker"))
        assertTrue(ics.contains("SUMMARY:Morning shift — Sam"))
        assertTrue(ics.contains("SUMMARY:Morning shift — Carol"))
    }

    @Test
    fun anchorsDatesToTheWeekStart() {
        // day 0 → 2026-06-22, day 1 → 2026-06-23
        val grid = listOf(listOf(listOf("A")), listOf(listOf("B")))
        val ics = buildScheduleIcs("R", listOf("Morning"), grid, mondayEpoch)
        assertTrue(ics.contains("DTSTART;VALUE=DATE:20260622"))
        assertTrue(ics.contains("DTSTART;VALUE=DATE:20260623"))
    }

    @Test
    fun emptyCellsProduceNoEvents() {
        val grid = listOf(listOf(listOf<String>(), listOf("Bob")))
        val ics = buildScheduleIcs("R", listOf("Morning", "Night"), grid, mondayEpoch)
        assertEquals(1, Regex("BEGIN:VEVENT").findAll(ics).count())
        assertTrue(ics.contains("Night shift — Bob"))
    }

    @Test
    fun emptyGridStillValidCalendar() {
        val ics = buildScheduleIcs("R", listOf("Morning"), emptyList(), mondayEpoch)
        assertTrue(ics.contains("BEGIN:VCALENDAR"))
        assertEquals(0, Regex("BEGIN:VEVENT").findAll(ics).count())
    }

    @Test
    fun filenameSanitized() {
        assertTrue(scheduleIcsFilename("QA Demo Schedule").startsWith("QA_Demo_Schedule"))
        assertTrue(scheduleIcsFilename("a/b:c?").endsWith(".ics"))
        assertTrue(scheduleIcsFilename("").startsWith("schedule"))
    }
}
