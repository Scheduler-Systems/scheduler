@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.schedule

import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
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

class ScheduleBuildViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var repository: ScheduleRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        repository = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `build success sets the grid and built flag`() = runTest {
        val grid = listOf(listOf(listOf("Alex", "", "QA")))
        coEvery { repository.getLatestBuiltSchedule("s1") } returns null
        coEvery { repository.buildAndSaveSchedule("s1") } returns Result.success(grid)
        val vm = ScheduleBuildViewModel(repository)
        advanceUntilIdle()

        vm.build("s1")
        advanceUntilIdle()

        val state = vm.state.value
        assertEquals(grid, state.grid)
        assertTrue(state.built)
        assertFalse(state.isLoading)
        assertNull(state.error)
    }

    @Test
    fun `build failure surfaces the error and clears loading`() = runTest {
        coEvery { repository.getLatestBuiltSchedule("s1") } returns null
        coEvery { repository.buildAndSaveSchedule("s1") } returns
            Result.failure(Exception("Schedule not found"))
        val vm = ScheduleBuildViewModel(repository)
        advanceUntilIdle()

        vm.build("s1")
        advanceUntilIdle()

        val state = vm.state.value
        assertTrue(state.grid.isEmpty())
        assertFalse(state.isLoading)
        assertEquals("Schedule not found", state.error)
    }

    @Test
    fun `load surfaces an already-built grid`() = runTest {
        val grid = listOf(listOf(listOf("Alex")))
        coEvery { repository.getLatestBuiltSchedule("s1") } returns grid
        val vm = ScheduleBuildViewModel(repository)

        vm.load("s1")
        advanceUntilIdle()

        assertEquals(grid, vm.state.value.grid)
        assertTrue(vm.state.value.built)
    }
}
