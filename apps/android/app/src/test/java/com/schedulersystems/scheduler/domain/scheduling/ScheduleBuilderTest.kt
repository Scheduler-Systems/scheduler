package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Characterization test: pins the Kotlin buildSchedule port to the canonical web
 * algorithm by reproducing scheduler-web/lib/schedule-builder.test.ts's golden cases.
 * If this and the iOS ScheduleBuilderTests agree with these goldens, all three match.
 */
class ScheduleBuilderTest {

    private val workers = listOf("Alice", "Bob", "Carol", "Dave")

    @Test
    fun `empty grid when no shifts`() {
        val out = buildSchedule(BuildScheduleInput(workers, emptyList(), 7, 1))
        assertTrue(out.rows.isEmpty())
    }

    @Test
    fun `empty grid when no days`() {
        val out = buildSchedule(BuildScheduleInput(workers, listOf("morning"), 0, 1))
        assertTrue(out.rows.isEmpty())
    }

    @Test
    fun `numDays times numShifts rows in day-major order`() {
        val out = buildSchedule(BuildScheduleInput(workers, listOf("morning", "night"), 3, 1))
        assertEquals(3 * 2, out.rows.size)
        assertEquals(1, out.rows[0].size)
        assertEquals(1, out.rows[1].size)
    }

    @Test
    fun `assigns numStations names per slot`() {
        val out = buildSchedule(BuildScheduleInput(workers, listOf("morning"), 1, 3))
        assertEquals(1, out.rows.size)
        assertEquals(3, out.rows[0].size)
    }

    @Test
    fun `cycles employees round-robin`() {
        val out = buildSchedule(BuildScheduleInput(listOf("A", "B", "C"), listOf("morning", "night"), 2, 1))
        assertEquals(listOf("A", "B", "C", "A"), out.rows.map { it[0] })
    }

    @Test
    fun `empty-string placeholders when no employees`() {
        val out = buildSchedule(BuildScheduleInput(emptyList(), listOf("morning"), 1, 2))
        assertEquals(listOf("", ""), out.rows[0])
    }

    @Test
    fun `flags a worker on two shifts same day`() {
        val out = buildSchedule(BuildScheduleInput(listOf("Solo"), listOf("morning", "night"), 1, 1))
        assertEquals(1, out.conflicts.size)
        assertEquals("Solo", out.conflicts[0].worker)
        assertEquals(0, out.conflicts[0].dayIndex)
        assertEquals(listOf("morning", "night"), out.conflicts[0].shifts)
    }

    @Test
    fun `no conflicts for a well-distributed build`() {
        val out = buildSchedule(BuildScheduleInput(workers, listOf("morning", "night"), 3, 1))
        assertTrue(out.conflicts.isEmpty())
    }

    @Test
    fun `avoidSameDayConflicts skips a worker already on the day`() {
        val out = buildSchedule(
            BuildScheduleInput(listOf("Solo"), listOf("morning", "night"), 1, 1, avoidSameDayConflicts = true)
        )
        assertEquals(listOf("Solo"), out.rows[0])
        assertEquals(listOf(""), out.rows[1])
        assertTrue(out.conflicts.isEmpty())
    }

    @Test
    fun `prefers a priority worker over round-robin`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("Alice", "Bob"), listOf("morning"), 1, 1,
                startWeekday = 0, // Sunday
                priorities = mapOf("bob" to setOf("Sun|morning"))
            )
        )
        assertEquals("Bob", out.rows[0][0])
    }

    @Test
    fun `matches priorities case-insensitively`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("Alice", "Bob"), listOf("morning"), 1, 1,
                startWeekday = 0,
                priorities = mapOf("BOB" to setOf("Sun|morning"))
            )
        )
        assertEquals("Bob", out.rows[0][0])
    }

    @Test
    fun `among tied priority candidates picks fewest assignments`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("Alice", "Bob", "Carol"), listOf("morning"), 2, 1,
                startWeekday = 0,
                priorities = mapOf("bob" to setOf("Sun|morning", "Mon|morning"), "carol" to setOf("Mon|morning"))
            )
        )
        assertEquals("Bob", out.rows[0][0])
        assertEquals("Carol", out.rows[1][0])
    }

    @Test
    fun `falls back to fairness round-robin when no priority match`() {
        val out = buildSchedule(
            BuildScheduleInput(listOf("A", "B", "C"), listOf("morning"), 3, 1, priorities = emptyMap())
        )
        assertEquals(listOf("A", "B", "C"), out.rows.map { it[0] })
    }

    @Test
    fun `respects avoidSameDayConflicts for priority picks`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("Solo", "Other"), listOf("morning", "night"), 1, 1,
                startWeekday = 0, avoidSameDayConflicts = true,
                priorities = mapOf("solo" to setOf("Sun|morning", "Sun|night"))
            )
        )
        assertEquals("Solo", out.rows[0][0])
        assertEquals("Other", out.rows[1][0])
    }

    @Test
    fun `priorities ignored when named worker not on roster`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("A", "B"), listOf("morning"), 1, 1,
                startWeekday = 0, priorities = mapOf("ghost" to setOf("Sun|morning"))
            )
        )
        assertEquals("A", out.rows[0][0])
    }

    @Test
    fun `handles trimmed whitespace in priority names`() {
        val out = buildSchedule(
            BuildScheduleInput(
                listOf("Alice", "Bob"), listOf("morning"), 1, 1,
                startWeekday = 0, priorities = mapOf("  bob  " to setOf("Sun|morning"))
            )
        )
        assertEquals("Bob", out.rows[0][0])
    }
}
