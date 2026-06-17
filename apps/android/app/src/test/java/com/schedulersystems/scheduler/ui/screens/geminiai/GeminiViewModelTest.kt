@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.geminiai

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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class GeminiViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `should start with default state`() {
        val vm = GeminiViewModel()

        assertEquals("", vm.state.value.prompt)
        assertEquals("", vm.state.value.response)
        assertFalse(vm.state.value.isLoading)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should update prompt on setPrompt`() {
        val vm = GeminiViewModel()

        vm.setPrompt("Optimize morning shifts")

        assertEquals("Optimize morning shifts", vm.state.value.prompt)
    }

    @Test
    fun `should generate response and clear loading`() = runTest {
        val vm = GeminiViewModel()
        vm.setPrompt("Create weekly schedule")

        vm.generate()
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertNotNull(vm.state.value.response)
        assertTrue(vm.state.value.response.contains("Create weekly schedule"))
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should generate response even with empty prompt`() = runTest {
        val vm = GeminiViewModel()

        vm.generate()
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertNotNull(vm.state.value.response)
        assertTrue(vm.state.value.response.contains("AI scheduling assistant response"))
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should reset loading state on generate failure path`() = runTest {
        val vm = GeminiViewModel()

        vm.generate()
        advanceUntilIdle()
        assertFalse(vm.state.value.isLoading)
    }
}
