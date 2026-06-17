package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test

class ShiftAssignerTest {

    @Test
    fun `should return output with correct dimensions for empty priorities`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 1,
            numOfPeople = 1
        )

        val result = assignShifts(input)
        assertEquals(1, result.assignments.size)
        assertEquals(21, result.assignments[0].size)
        assertEquals(1, result.grids.size)
        assertEquals(7, result.grids[0].size)
    }

    @Test
    fun `should produce grids of correct dimensions`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 3,
            numOfPeople = 1
        )

        val result = assignShifts(input)
        assertEquals(3, result.assignments.size)
        assertEquals(3, result.grids.size)
        result.assignments.forEach { assertEquals(21, it.size) }
    }

    @Test
    fun `should handle single station`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 1,
            numOfPeople = 1
        )

        val result = assignShifts(input)
        assertNotNull(result)
        assertEquals(1, result.assignments.size)
    }

    @Test
    fun `should accept partial station configs`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 2,
            numOfPeople = 1,
            stations = listOf(
                PartialStationConfig(morning = true, afternoon = false, night = false),
                PartialStationConfig(morning = false, afternoon = true, night = true)
            )
        )

        val result = assignShifts(input)
        assertEquals(2, result.assignments.size)
    }

    @Test
    fun `should handle default configs for missing station overrides`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 3,
            numOfPeople = 1,
            stations = listOf(
                PartialStationConfig(morning = true, afternoon = false, night = false)
            )
        )

        val result = assignShifts(input)
        assertEquals(3, result.assignments.size)
    }

    @Test
    fun `should handle all false station config`() {
        val input = AssignShiftsInput(
            currentPriorities = (0 until 21).map { "" },
            stationNum = 1,
            numOfPeople = 1,
            stations = listOf(
                PartialStationConfig(morning = false, afternoon = false, night = false)
            )
        )

        val result = assignShifts(input)
        assertEquals(1, result.assignments.size)
    }
}
