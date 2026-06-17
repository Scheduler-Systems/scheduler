@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.onboarding

import app.cash.turbine.test
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.User
import com.schedulersystems.scheduler.ui.screens.schedule.ScheduleListViewModel
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
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

class ScheduleListViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var scheduleRepository: ScheduleRepository
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        scheduleRepository = mockk()
        authRepository = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `should show loading initially`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(user)
        every { scheduleRepository.getSchedulesForUser("user-1") } returns flowOf(emptyList())

        val vm = ScheduleListViewModel(scheduleRepository, authRepository)

        assertEquals(true, vm.state.value.isLoading)
    }

    @Test
    fun `should load schedules and set loading false`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        val mockSchedules = listOf(
            Schedule("s-1", "Schedule A", "t-1", emptyList(), emptyList(),
                ScheduleSettings(null,
                    EnabledShifts(true, true, false), "UTC"),
                emptyList(), Instant.now(), Instant.now())
        )

        every { authRepository.currentUser } returns flowOf(user)
        every { scheduleRepository.getSchedulesForUser("user-1") } returns flowOf(mockSchedules)

        val vm = ScheduleListViewModel(scheduleRepository, authRepository)
        advanceUntilIdle()

        vm.state.test {
            val state = awaitItem()
            assertFalse(state.isLoading)
            assertEquals(1, state.schedules.size)
            assertEquals("Schedule A", state.schedules[0].name)
            assertTrue(state.initCompleted)
        }
    }

    @Test
    fun `should handle null user gracefully`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)

        val vm = ScheduleListViewModel(scheduleRepository, authRepository)
        advanceUntilIdle()

        vm.state.test {
            val state = awaitItem()
            assertFalse(state.isLoading)
            assertTrue(state.schedules.isEmpty())
            assertTrue(state.initCompleted)
        }
    }

    @Test
    fun `should start loading on refresh`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(user)
        every { scheduleRepository.getSchedulesForUser("user-1") } returns flowOf(emptyList())

        val vm = ScheduleListViewModel(scheduleRepository, authRepository)
        advanceUntilIdle()

        vm.refresh()

        assertEquals(true, vm.state.value.isLoading)
    }
}
