@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.export

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
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

class ExportShiftsViewModelTest {

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

    @Test
    fun `should start with loading state`() {
        val vm = ExportShiftsViewModel(scheduleRepository)

        assertTrue(vm.state.value.isLoading)
        assertEquals("", vm.state.value.scheduleName)
        assertFalse(vm.state.value.isExporting)
        assertFalse(vm.state.value.isExported)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should load schedule name on valid scheduleId`() = runTest {
        val schedule = Schedule(
            id = "s-1",
            name = "Weekly Roster",
            tenantId = "t-1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            nextSchedule = emptyList(),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ExportShiftsViewModel(scheduleRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals("Weekly Roster", vm.state.value.scheduleName)
    }

    @Test
    fun `should handle null schedule gracefully`() = runTest {
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = ExportShiftsViewModel(scheduleRepository)
        vm.loadSchedule("invalid-id")
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals("", vm.state.value.scheduleName)
    }

    @Test
    fun `should export to google calendar successfully`() = runTest {
        coEvery { scheduleRepository.getScheduleById(any()) } returns null

        val vm = ExportShiftsViewModel(scheduleRepository)
        vm.exportToGoogleCalendar("s-1")
        advanceUntilIdle()

        assertFalse(vm.state.value.isExporting)
        assertTrue(vm.state.value.isExported)
    }

    @Test
    fun `should reload schedule on subsequent loadSchedule call`() = runTest {
        val schedule = Schedule(
            id = "s-1",
            name = "Final Roster",
            tenantId = "t-1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            nextSchedule = emptyList(),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ExportShiftsViewModel(scheduleRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        assertEquals("Final Roster", vm.state.value.scheduleName)
        assertFalse(vm.state.value.isLoading)

        vm.loadSchedule("s-1")
    }
}
