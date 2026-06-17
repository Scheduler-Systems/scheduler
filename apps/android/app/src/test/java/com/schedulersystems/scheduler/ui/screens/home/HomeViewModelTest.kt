@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.home

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
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

class HomeViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `should start with loading state`() {
        val vm = HomeViewModel(authRepository)

        assertTrue(vm.state.value.isLoading)
        assertNull(vm.state.value.displayName)
        assertNull(vm.state.value.userRole)
        assertFalse(vm.state.value.isPremium)
    }

    @Test
    fun `should load user data on initialization`() = runTest {
        val user = User("user-1", "test@test.com", null, "Alice", Role.ADMIN, true, null)
        every { authRepository.currentUser } returns flowOf(user)

        val vm = HomeViewModel(authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals("Alice", vm.state.value.displayName)
        assertEquals(Role.ADMIN, vm.state.value.userRole)
        assertTrue(vm.state.value.isPremium)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should handle null user gracefully`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)

        val vm = HomeViewModel(authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertNull(vm.state.value.displayName)
        assertNull(vm.state.value.userRole)
        assertFalse(vm.state.value.isPremium)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should update state when user emits new value`() = runTest {
        val user1 = User("user-1", "old@test.com", null, "Old Name", Role.EMPLOYEE, false, null)
        val user2 = User("user-1", "new@test.com", null, "New Name", Role.EMPLOYER, true, null)

        every { authRepository.currentUser } returns flowOf(user1, user2)

        val vm = HomeViewModel(authRepository)
        advanceUntilIdle()

        assertEquals("New Name", vm.state.value.displayName)
        assertEquals(Role.EMPLOYER, vm.state.value.userRole)
        assertTrue(vm.state.value.isPremium)
    }
}
