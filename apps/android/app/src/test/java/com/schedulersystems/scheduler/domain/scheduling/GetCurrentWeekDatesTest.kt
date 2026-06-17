package com.schedulersystems.scheduler.domain.scheduling

import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Calendar
import java.util.Date

class GetCurrentWeekDatesTest {

    @Test
    fun `should return 7 dates`() {
        val result = getCurrentWeekDates(false)
        assertEquals(7, result.size)
    }

    @Test
    fun `should return 7 dates when deadline is over`() {
        val result = getCurrentWeekDates(true)
        assertEquals(7, result.size)
    }

    @Test
    fun `getWeekDates should return 7 dates`() {
        val result = getWeekDates(Date())
        assertEquals(7, result.size)
    }

    @Test
    fun `dates should be in ascending order`() {
        val result = getWeekDates(Date())
        for (i in 1 until result.size) {
            assert(result[i].after(result[i - 1]) || result[i] == result[i - 1])
        }
    }
}
