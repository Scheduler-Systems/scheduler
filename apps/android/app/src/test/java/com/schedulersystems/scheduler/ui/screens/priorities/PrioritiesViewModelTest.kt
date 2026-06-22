@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.priorities

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
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

class PrioritiesViewModelTest {

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

    private fun createMockSchedule(
        priorities: List<String> = emptyList(),
        employees: List<Employee> = emptyList()
    ): Schedule {
        return Schedule(
            id = "s-1",
            name = "Test Schedule",
            tenantId = "t-1",
            employees = employees,
            currentPriorities = priorities,
            settings = ScheduleSettings(
                submissionDeadline = null,
                enabledShifts = EnabledShifts(true, true, false),
                timezone = "UTC"
            ),
            nextSchedule = emptyList(),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
    }

    @Test
    fun `initial state should have loading true and empty data`() {
        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        val state = vm.state.value

        assertTrue(state.isLoading)
        assertTrue(state.priorities.isEmpty())
        assertTrue(state.submittedPriorities.isEmpty())
        assertTrue(state.employees.isEmpty())
        assertFalse(state.isSubmitting)
        assertFalse(state.isSubmitted)
        assertNull(state.error)
    }

    @Test
    fun `loadPriorities should populate priorities employees and submitted flags`() = runTest {
        val priorities = listOf("Morning", "Afternoon", "Evening")
        val employees = listOf(
            Employee("e-1", "Alice", "alice@test.com", null, Role.EMPLOYEE, emptyMap()),
            Employee("e-2", "Bob", "bob@test.com", null, Role.EMPLOYEE, emptyMap())
        )
        val schedule = createMockSchedule(priorities, employees)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals(3, state.priorities.size)
        assertEquals("Morning", state.priorities[0])
        assertEquals("Afternoon", state.priorities[1])
        assertEquals("Evening", state.priorities[2])
        assertEquals(3, state.submittedPriorities.size)
        assertFalse(state.submittedPriorities.any { it })
        assertEquals(2, state.employees.size)
        assertEquals("Alice", state.employees[0])
        assertEquals("Bob", state.employees[1])
    }

    @Test
    fun `loadPriorities should set error when schedule is null`() = runTest {
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("invalid-id")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.priorities.isEmpty())
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `togglePriority should toggle submitted state at given index`() = runTest {
        val priorities = listOf("Morning", "Afternoon")
        val schedule = createMockSchedule(priorities)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()

        assertFalse(vm.state.value.submittedPriorities[0])

        vm.togglePriority(0)

        assertTrue(vm.state.value.submittedPriorities[0])
        assertFalse(vm.state.value.submittedPriorities[1])
    }

    @Test
    fun `togglePriority should toggle back to false when called twice`() = runTest {
        val priorities = listOf("Morning", "Afternoon")
        val schedule = createMockSchedule(priorities)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()

        vm.togglePriority(1)
        assertTrue(vm.state.value.submittedPriorities[1])

        vm.togglePriority(1)
        assertFalse(vm.state.value.submittedPriorities[1])
    }

    @Test
    fun `togglePriority should preserve other indices when toggling`() = runTest {
        val priorities = listOf("Morning", "Afternoon", "Evening")
        val schedule = createMockSchedule(priorities)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()

        vm.togglePriority(0)
        vm.togglePriority(2)

        assertTrue(vm.state.value.submittedPriorities[0])
        assertFalse(vm.state.value.submittedPriorities[1])
        assertTrue(vm.state.value.submittedPriorities[2])
    }

    @Test
    fun `submitPriorities submits selected priorities and sets isSubmitted on success`() = runTest {
        val priorities = listOf("Alex Worker", "QA Verified")
        coEvery { scheduleRepository.getScheduleById("s-1") } returns createMockSchedule(priorities)
        val captured = slot<Map<String, Any>>()
        coEvery { scheduleRepository.submitAvailability(eq("s-1"), capture(captured)) } returns Result.success(Unit)

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()
        vm.togglePriority(0) // select "Alex Worker"
        vm.submitPriorities("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSubmitting)
        assertTrue(state.isSubmitted)
        assertNull(state.error)
        // The real availability call was made with the full order + the selected slot.
        coVerify(exactly = 1) { scheduleRepository.submitAvailability(eq("s-1"), any()) }
        assertEquals(listOf("Alex Worker", "QA Verified"), captured.captured["priorities"])
        assertEquals(listOf("Alex Worker"), captured.captured["selected"])
    }

    @Test
    fun `submitPriorities surfaces error and does not mark submitted on failure`() = runTest {
        coEvery { scheduleRepository.getScheduleById("s-1") } returns createMockSchedule(listOf("Alex Worker"))
        coEvery { scheduleRepository.submitAvailability(any(), any()) } returns
            Result.failure(Exception("network down"))

        val vm = PrioritiesViewModel(scheduleRepository, authRepository)
        vm.loadPriorities("s-1")
        advanceUntilIdle()
        vm.submitPriorities("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isSubmitting)
        assertFalse(state.isSubmitted)
        assertEquals("network down", state.error)
    }
}
