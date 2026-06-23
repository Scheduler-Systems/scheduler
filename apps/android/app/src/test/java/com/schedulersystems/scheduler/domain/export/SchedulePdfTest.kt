package com.schedulersystems.scheduler.domain.export

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Characterization tests for the pure schedule-PDF model. Mirrors the behaviors
 * pinned by the web's lib/pdf-export.test.ts (title/filename/row-expansion) so the
 * native PDF stays faithful to the canonical reference.
 */
class SchedulePdfTest {

    // --- title -------------------------------------------------------------

    @Test
    fun title_includesNameAndDateRange() {
        val t = schedulePdfTitle("Summer Team", "2026-05-03", "2026-05-09")
        assertTrue(t.contains("Summer Team"))
        assertTrue(t.contains("Schedule"))
        assertTrue(t.contains("2026-05-03"))
        assertTrue(t.contains("2026-05-09"))
    }

    @Test
    fun title_defaultsToUntitledWhenBlank() {
        val t = schedulePdfTitle("")
        assertTrue(t.contains("Untitled"))
        assertTrue(t.contains("Schedule"))
    }

    @Test
    fun title_omitsRangeWhenBothWeekdaysBlank() {
        assertEquals("My Roster Schedule", schedulePdfTitle("My Roster", "", ""))
    }

    @Test
    fun title_includesOnlyFirstWhenLastBlank() {
        assertTrue(schedulePdfTitle("R", "2026-05-03", "").contains("2026-05-03"))
    }

    @Test
    fun title_includesOnlyLastWhenFirstBlank() {
        assertTrue(schedulePdfTitle("R", "", "2026-05-09").contains("2026-05-09"))
    }

    // --- filename ----------------------------------------------------------

    @Test
    fun filename_usesScheduleName() {
        assertTrue(schedulePdfFilename("Q2 Roster").matches(Regex("^Q2_Roster.*\\.pdf$")))
    }

    @Test
    fun filename_sanitizesUnsafeCharacters() {
        val name = schedulePdfFilename("Team / Week: 21?")
        assertTrue(!name.contains("/") && !name.contains(":") && !name.contains("?"))
        assertTrue(name.endsWith(".pdf"))
    }

    @Test
    fun filename_fallsBackWhenBlank() {
        assertTrue(schedulePdfFilename("").lowercase().startsWith("schedule"))
    }

    @Test
    fun filename_trimsWhitespace() {
        assertTrue(schedulePdfFilename("  My Roster  ").startsWith("My_Roster"))
    }

    @Test
    fun filename_fallsBackWhenOnlySpecialChars() {
        assertTrue(schedulePdfFilename("___").startsWith("schedule"))
    }

    // --- row expansion -----------------------------------------------------

    @Test
    fun rows_headerOrderIsShiftDayEmployee() {
        assertEquals(listOf("Shift", "Day", "Employee"), SchedulePdfDoc.HEADER)
    }

    @Test
    fun rows_expandDayMajorOneRowPerWorker() {
        // 2 days x 1 shift; first cell has two workers -> two rows for that cell.
        val grid = listOf(
            listOf(listOf("Alice", "Bob")), // day 0, shift 0
            listOf(listOf("Carol"))         // day 1, shift 0
        )
        val rows = buildSchedulePdfRows(listOf("Morning"), grid)
        assertEquals(3, rows.size)
        assertEquals("Alice", rows[0].employee)
        assertEquals("Bob", rows[1].employee)
        assertEquals("Morning", rows[0].shift)
        assertEquals(rows[0].day, rows[1].day) // same day label for the same cell
        assertEquals("Carol", rows[2].employee)
    }

    @Test
    fun rows_emptyCellYieldsPlaceholderRow() {
        val grid = listOf(
            listOf(listOf<String>(), listOf("Bob"))
        )
        val rows = buildSchedulePdfRows(listOf("Morning", "Night"), grid)
        assertEquals(2, rows.size)
        assertEquals("", rows[0].employee) // placeholder for the empty morning cell
        assertEquals("Bob", rows[1].employee)
    }

    @Test
    fun rows_handleNoEnabledShiftsGracefully() {
        val rows = buildSchedulePdfRows(emptyList(), listOf(listOf(listOf("X"))))
        assertTrue(rows.isNotEmpty())
        assertEquals("X", rows[0].employee)
    }

    @Test
    fun doc_combinesTitleFilenameRows() {
        val doc = buildSchedulePdfDoc(
            scheduleName = "QA Demo Schedule",
            enabledShifts = listOf("Morning"),
            grid = listOf(listOf(listOf("Alex Worker")))
        )
        assertEquals("QA Demo Schedule Schedule", doc.title)
        assertTrue(doc.filename.startsWith("QA_Demo_Schedule"))
        assertEquals("Alex Worker", doc.rows[0].employee)
    }
}
