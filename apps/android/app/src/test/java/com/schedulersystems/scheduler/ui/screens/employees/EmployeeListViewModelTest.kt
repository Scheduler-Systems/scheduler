@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.employees

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.ShiftRow
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

class EmployeeListViewModelTest {

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

    private fun createMockSchedule(employees: List<Employee> = emptyList()): Schedule {
        return Schedule(
            id = "s-1",
            name = "Test Schedule",
            tenantId = "t-1",
            employees = employees,
            currentPriorities = emptyList(),
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

    private fun createMockEmployee(
        id: String = "e-1",
        name: String = "Alice",
        email: String? = "alice@test.com",
        phone: String? = null
    ): Employee {
        return Employee(
            id = id,
            name = name,
            email = email,
            phone = phone,
            role = Role.EMPLOYEE,
            priorityMap = emptyMap()
        )
    }

    @Test
    fun `loadEmployees should populate state with employees from schedule`() = runTest {
        val employees = listOf(
            createMockEmployee(id = "e-1", name = "Alice"),
            createMockEmployee(id = "e-2", name = "Bob")
        )
        val schedule = createMockSchedule(employees)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertEquals(2, state.employees.size)
        assertEquals("Alice", state.employees[0].name)
        assertEquals("Bob", state.employees[1].name)
        assertEquals("Test Schedule", state.scheduleName)
        assertEquals("s-1", state.scheduleId)
    }

    @Test
    fun `loadEmployees should handle null schedule and set error`() = runTest {
        coEvery { scheduleRepository.getScheduleById("invalid-id") } returns null

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("invalid-id")
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isLoading)
        assertTrue(state.employees.isEmpty())
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `addEmployee should add employee and reload`() = runTest {
        val initialEmployees = listOf(createMockEmployee(id = "e-1", name = "Alice"))
        val schedule = createMockSchedule(initialEmployees)
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.addEmployee(eq("s-1"), any()) } returns Result.success(Unit)

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        vm.setName("Charlie")
        vm.setEmail("charlie@test.com")
        vm.setPhone("+1234567890")

        vm.addEmployee("s-1")
        advanceUntilIdle()

        val addState = vm.addState.value
        assertFalse(addState.isAdding)
        assertTrue(addState.isAdded)
        // Fields should be cleared after successful add
        assertEquals("", addState.email)
        assertEquals("", addState.name)
        assertEquals("", addState.phone)
    }

    @Test
    fun `addEmployee should handle failure`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.addEmployee(eq("s-1"), any()) } returns
            Result.failure(Exception("Failed to add employee"))

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        vm.setName("Charlie")
        vm.addEmployee("s-1")
        advanceUntilIdle()

        val addState = vm.addState.value
        assertFalse(addState.isAdding)
        assertFalse(addState.isAdded)
        assertEquals("Failed to add employee", addState.error)
    }

    @Test
    fun `removeEmployee should remove employee and reload`() = runTest {
        val twoEmployeeSchedule = createMockSchedule(listOf(
            createMockEmployee(id = "e-1", name = "Alice"),
            createMockEmployee(id = "e-2", name = "Bob")
        ))
        val oneEmployeeSchedule = createMockSchedule(listOf(
            createMockEmployee(id = "e-1", name = "Alice")
        ))
        var callCount = 0
        coEvery { scheduleRepository.getScheduleById("s-1") } answers {
            callCount++
            if (callCount >= 2) oneEmployeeSchedule else twoEmployeeSchedule
        }
        coEvery { scheduleRepository.removeEmployee("s-1", "e-2") } returns Result.success(Unit)

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        assertEquals(2, vm.state.value.employees.size)

        vm.removeEmployee("s-1", "e-2")
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals(1, state.employees.size)
        assertEquals("Alice", state.employees[0].name)
    }

    @Test
    fun `removeEmployee should handle failure`() = runTest {
        val schedule = createMockSchedule(listOf(createMockEmployee(id = "e-1")))
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.removeEmployee("s-1", "e-1") } returns
            Result.failure(Exception("Failed to remove employee"))

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        vm.removeEmployee("s-1", "e-1")
        advanceUntilIdle()

        assertEquals("Failed to remove employee", vm.state.value.error)
    }

    @Test
    fun `setEmail should update add state email field`() = runTest {
        val vm = EmployeeListViewModel(scheduleRepository)

        vm.setEmail("newemail@test.com")

        assertEquals("newemail@test.com", vm.addState.value.email)
    }

    @Test
    fun `setName should update add state name field`() = runTest {
        val vm = EmployeeListViewModel(scheduleRepository)

        vm.setName("New Employee")

        assertEquals("New Employee", vm.addState.value.name)
    }

    @Test
    fun `setPhone should update add state phone field`() = runTest {
        val vm = EmployeeListViewModel(scheduleRepository)

        vm.setPhone("+9876543210")

        assertEquals("+9876543210", vm.addState.value.phone)
    }

    @Test
    fun `addEmployee with empty fields should still create employee`() = runTest {
        val schedule = createMockSchedule()
        coEvery { scheduleRepository.getScheduleById("s-1") } returns schedule
        coEvery { scheduleRepository.addEmployee(eq("s-1"), any()) } returns Result.success(Unit)

        val vm = EmployeeListViewModel(scheduleRepository)
        vm.loadEmployees("s-1")
        advanceUntilIdle()

        // Add employee with only name set
        vm.setName("Dave")
        vm.addEmployee("s-1")
        advanceUntilIdle()

        assertTrue(vm.addState.value.isAdded)
    }
}
