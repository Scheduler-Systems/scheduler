@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.schedule

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Schedule
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.slot
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

class NewScheduleViewModelTest {

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
    fun `create posts schedule with the entered name and flips created`() = runTest {
        val captured = slot<Schedule>()
        coEvery { scheduleRepository.createSchedule(capture(captured)) } returns Result.success("new-id")

        val vm = NewScheduleViewModel(scheduleRepository)
        vm.setName("Spring Roster")
        vm.create()
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isCreating)
        assertTrue(state.created)
        assertEquals("Spring Roster", captured.captured.name)
        coVerify(exactly = 1) { scheduleRepository.createSchedule(any()) }
    }

    @Test
    fun `create surfaces failure and does not mark created`() = runTest {
        coEvery { scheduleRepository.createSchedule(any()) } returns
            Result.failure(Exception("schedule_name_taken"))

        val vm = NewScheduleViewModel(scheduleRepository)
        vm.setName("Dup Name")
        vm.create()
        advanceUntilIdle()

        val state = vm.state.value
        assertFalse(state.isCreating)
        assertFalse(state.created)
        assertEquals("schedule_name_taken", state.error)
    }

    @Test
    fun `create with blank name validates without calling the repo`() = runTest {
        val vm = NewScheduleViewModel(scheduleRepository)
        vm.setName("   ")
        vm.create()
        advanceUntilIdle()

        assertFalse(vm.state.value.created)
        assertEquals("Name is required", vm.state.value.error)
        coVerify(exactly = 0) { scheduleRepository.createSchedule(any()) }
    }

    @Test
    fun `setName updates state`() = runTest {
        val vm = NewScheduleViewModel(scheduleRepository)
        vm.setName("Weekly")
        assertEquals("Weekly", vm.state.value.name)
    }
}
