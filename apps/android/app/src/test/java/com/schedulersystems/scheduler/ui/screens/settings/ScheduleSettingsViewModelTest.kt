@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.settings

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.SubmissionDeadline
import io.mockk.coEvery
import io.mockk.every
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

class ScheduleSettingsViewModelTest {

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

    private fun createMockSchedule(settings: ScheduleSettings = ScheduleSettings(
        submissionDeadline = SubmissionDeadline(enabled = false, deadline = null),
        enabledShifts = EnabledShifts(mornings = true, afternoons = true, evenings = false),
        timezone = "UTC"
    )): Schedule {
        return Schedule(
            id = "s-1",
            name = "Test Schedule",
            tenantId = "t-1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = settings,
            nextSchedule = emptyList(),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
    }

    @Test
    fun `loadSettings should populate state from schedule`() = runTest {
        val settings = ScheduleSettings(
            submissionDeadline = SubmissionDeadline(enabled = true, deadline = Instant.now()),
            enabledShifts = EnabledShifts(mornings = true, afternoons = false, evenings = true),
            timezone = "America/New_York"
        )
        val schedule = createMockSchedule(settings)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals("Test Schedule", state.scheduleName)
        assertTrue(state.enabledShifts.mornings)
        assertFalse(state.enabledShifts.afternoons)
        assertTrue(state.enabledShifts.evenings)
        assertTrue(state.submissionDeadlineEnabled)
        assertEquals("America/New_York", state.timezone)
    }

    @Test
    fun `loadSettings should handle null schedule and set error`() = runTest {
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("invalid-id")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `loadSettings should default submissionDeadline to false when null`() = runTest {
        val settings = ScheduleSettings(
            submissionDeadline = null,
            enabledShifts = EnabledShifts(true, true, false),
            timezone = "UTC"
        )
        val schedule = createMockSchedule(settings)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("s-1")
        advanceUntilIdle()

        assertFalse(vm.state.value.submissionDeadlineEnabled)
    }

    @Test
    fun `toggleMorning should update morning shifts`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        assertFalse(vm.state.value.enabledShifts.mornings)

        vm.toggleMorning(true)
        assertTrue(vm.state.value.enabledShifts.mornings)

        vm.toggleMorning(false)
        assertFalse(vm.state.value.enabledShifts.mornings)
    }

    @Test
    fun `toggleAfternoon should update afternoon shifts`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        vm.toggleAfternoon(true)
        assertTrue(vm.state.value.enabledShifts.afternoons)

        vm.toggleAfternoon(false)
        assertFalse(vm.state.value.enabledShifts.afternoons)
    }

    @Test
    fun `toggleEvening should update evening shifts`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        vm.toggleEvening(true)
        assertTrue(vm.state.value.enabledShifts.evenings)

        vm.toggleEvening(false)
        assertFalse(vm.state.value.enabledShifts.evenings)
    }

    @Test
    fun `toggleDeadline should update submission deadline`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        vm.toggleDeadline(true)
        assertTrue(vm.state.value.submissionDeadlineEnabled)

        vm.toggleDeadline(false)
        assertFalse(vm.state.value.submissionDeadlineEnabled)
    }

    @Test
    fun `setDeadlineDay should update deadline day`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        vm.setDeadlineDay("Friday")

        assertEquals("Friday", vm.state.value.deadlineDay)
    }

    @Test
    fun `setTimezone should update timezone`() = runTest {
        val vm = ScheduleSettingsViewModel(scheduleRepository)

        vm.setTimezone("Europe/London")

        assertEquals("Europe/London", vm.state.value.timezone)
    }

    @Test
    fun `saveSettings should save successfully with deadline enabled`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.updateSchedule(any()) } returns Result.success(Unit)

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("s-1")
        advanceUntilIdle()

        vm.toggleMorning(true)
        vm.toggleEvening(true)
        vm.toggleDeadline(true)
        vm.setTimezone("America/Chicago")

        vm.saveSettings("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSaving)
        assertTrue(state.isSaved)
    }

    @Test
    fun `saveSettings should save successfully with deadline disabled`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.updateSchedule(any()) } returns Result.success(Unit)

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("s-1")
        advanceUntilIdle()

        vm.saveSettings("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSaving)
        assertTrue(state.isSaved)
    }

    @Test
    fun `saveSettings should handle update failure`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.updateSchedule(any()) } returns
            Result.failure(Exception("Network error"))

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.loadSettings("s-1")
        advanceUntilIdle()

        vm.saveSettings("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSaving)
        assertFalse(state.isSaved)
        assertEquals("Network error", state.error)
    }

    @Test
    fun `saveSettings should handle null schedule`() = runTest {
        coEvery { scheduleRepository.getScheduleById("s-1") } returns null

        val vm = ScheduleSettingsViewModel(scheduleRepository)
        vm.saveSettings("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSaving)
        assertEquals("Schedule not found", state.error)
    }
}
