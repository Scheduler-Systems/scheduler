@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.shift

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.Shift
import com.schedulersystems.scheduler.models.domain.ShiftRow
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.Instant
import java.time.LocalTime

class ShiftViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var scheduleRepository: ScheduleRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        scheduleRepository = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    private fun createMockSchedule(shiftRows: List<ShiftRow> = emptyList()): Schedule {
        return Schedule(
            id = "s-1",
            name = "Test Schedule",
            tenantId = "t-1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = ScheduleSettings(
                submissionDeadline = null,
                enabledShifts = EnabledShifts(true, true, false),
                timezone = "UTC"
            ),
            nextSchedule = shiftRows,
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
    }

    @Test
    fun `initial state should have loading true and empty shifts`() {
        val vm = ShiftViewModel(scheduleRepository)
        val state = vm.state.value

        assertTrue(state.isLoading)
        assertTrue(state.shiftRows.isEmpty())
        assertNull(state.error)
    }

    @Test
    fun `loadShifts should populate shift rows when schedule exists`() = runTest {
        val shiftRows = listOf(
            ShiftRow(
                shifts = listOf(
                    Shift("Mon", LocalTime.of(7, 0), LocalTime.of(13, 0), "Alice"),
                    Shift("Mon", LocalTime.of(14, 0), LocalTime.of(20, 0), null)
                )
            ),
            ShiftRow(
                shifts = listOf(
                    Shift("Tue", LocalTime.of(7, 0), LocalTime.of(13, 0), "Bob")
                )
            )
        )
        val schedule = createMockSchedule(shiftRows)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ShiftViewModel(scheduleRepository)
        vm.loadShifts("s-1", null)
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals(2, state.shiftRows.size)
        assertEquals("Mon", state.shiftRows[0].shifts[0].day)
        assertEquals(LocalTime.of(7, 0), state.shiftRows[0].shifts[0].startTime)
        assertEquals("Alice", state.shiftRows[0].shifts[0].assignedWorker)
        assertEquals("Tue", state.shiftRows[1].shifts[0].day)
        assertNull(state.error)
    }

    @Test
    fun `loadShifts should handle empty no shifts and keep error null`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ShiftViewModel(scheduleRepository)
        vm.loadShifts("s-1", null)
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.shiftRows.isEmpty())
        assertNull(state.error)
    }

    @Test
    fun `loadShifts should set error when schedule is not found`() = runTest {
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = ShiftViewModel(scheduleRepository)
        vm.loadShifts("invalid-id", null)
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.shiftRows.isEmpty())
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `loadShifts should start with loading state`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ShiftViewModel(scheduleRepository)

        vm.loadShifts("s-1", null)
        assertTrue(vm.state.value.isLoading)
    }
}
