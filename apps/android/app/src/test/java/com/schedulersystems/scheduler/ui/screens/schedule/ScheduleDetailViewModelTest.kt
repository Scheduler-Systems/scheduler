@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.schedule

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.Shift
import com.schedulersystems.scheduler.models.domain.ShiftRow
import com.schedulersystems.scheduler.models.domain.User
import io.mockk.coEvery
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.time.Instant
import java.time.LocalTime

class ScheduleDetailViewModelTest {

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

    private fun createMockSchedule(shiftRows: List<ShiftRow> = emptyList()): Schedule {
        return Schedule(
            id = "s-1",
            name = "Weekly Schedule",
            tenantId = "t-1",
            employees = listOf(
                Employee("e-1", "Alice", "alice@test.com", null, Role.EMPLOYEE, emptyMap())
            ),
            currentPriorities = listOf("Morning", "Afternoon"),
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

    private fun createMockUser(role: Role = Role.EMPLOYEE): User {
        return User(
            id = "user-1",
            email = "user@test.com",
            phone = null,
            displayName = "Test User",
            role = role,
            isPremium = false,
            tenantId = null
        )
    }

    @Test
    fun `loadSchedule should populate state when schedule exists`() = runTest {
        val shiftRows = listOf(
            ShiftRow(shifts = listOf(Shift("Mon", LocalTime.of(7, 0), LocalTime.of(13, 0), null))),
            ShiftRow(shifts = listOf(Shift("Tue", LocalTime.of(7, 0), LocalTime.of(13, 0), null)))
        )
        val schedule = createMockSchedule(shiftRows)
        val user = createMockUser(Role.EMPLOYER)

        every { authRepository.currentUser } returns flowOf(user)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.schedule != null)
        assertEquals("Weekly Schedule", state.schedule!!.name)
        assertEquals(Role.EMPLOYER, state.userRole)
    }

    @Test
    fun `loadSchedule should calculate schedule count`() = runTest {
        val shiftRows = listOf(
            ShiftRow(shifts = listOf(Shift("Mon", LocalTime.of(7, 0), LocalTime.of(13, 0), null))),
            ShiftRow(shifts = listOf(Shift("Tue", LocalTime.of(7, 0), LocalTime.of(13, 0), null))),
            ShiftRow(shifts = listOf(Shift("Wed", LocalTime.of(7, 0), LocalTime.of(13, 0), null)))
        )
        val schedule = createMockSchedule(shiftRows)
        val user = createMockUser()

        every { authRepository.currentUser } returns flowOf(user)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        assertEquals(3, vm.state.value.scheduleCount)
    }

    @Test
    fun `loadSchedule should handle null schedule and set error`() = runTest {
        val user = createMockUser()
        every { authRepository.currentUser } returns flowOf(user)
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)
        vm.loadSchedule("invalid-id")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertNull(state.schedule)
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `loadSchedule should handle null user`() = runTest {
        val schedule = createMockSchedule()
        every { authRepository.currentUser } returns flowOf(null)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.schedule != null)
        assertNull(state.userRole)
    }

    @Test
    fun `loadSchedule should start with loading state`() = runTest {
        val schedule = createMockSchedule()
        val user = createMockUser()
        every { authRepository.currentUser } returns flowOf(user)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)

        vm.loadSchedule("s-1")
        assertTrue(vm.state.value.isLoading)
    }

    @Test
    fun `loadSchedule should handle empty shift rows`() = runTest {
        val schedule = createMockSchedule() // empty shiftRows
        val user = createMockUser()
        every { authRepository.currentUser } returns flowOf(user)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = ScheduleDetailViewModel(scheduleRepository, authRepository)
        vm.loadSchedule("s-1")
        advanceUntilIdle()

        assertEquals(0, vm.state.value.scheduleCount)
        assertEquals(0.0, vm.state.value.attendancePercentage, 0.001)
    }
}
