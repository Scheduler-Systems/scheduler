@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.priority

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.Instant

class CurrentPrioritiesViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var scheduleRepository: ScheduleRepository

    @Before fun setup() { Dispatchers.setMain(testDispatcher); scheduleRepository = mockk() }
    @After fun tearDown() { Dispatchers.resetMain() }

    private fun schedule(priorities: List<String>) = Schedule(
        id = "s-1", name = "Test", tenantId = "t-1", employees = emptyList(),
        currentPriorities = priorities,
        settings = ScheduleSettings(null, EnabledShifts(false, false, false), "UTC"),
        nextSchedule = emptyList(), createdAt = Instant.now(), updatedAt = Instant.now()
    )

    @Test
    fun `loadCurrentPriorities populates the standings from the schedule`() = runTest {
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule(listOf("Alex Worker", "QA Verified"))
        val vm = CurrentPrioritiesViewModel(scheduleRepository)
        vm.loadCurrentPriorities("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals(listOf("Alex Worker", "QA Verified"), state.priorities)
        assertEquals(null, state.error)
    }

    @Test
    fun `loadCurrentPriorities sets error when schedule is null`() = runTest {
        coEvery { scheduleRepository.getScheduleById("bad") } returns null
        val vm = CurrentPrioritiesViewModel(scheduleRepository)
        vm.loadCurrentPriorities("bad")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.priorities.isEmpty())
        assertEquals("Schedule not found", state.error)
    }
}
