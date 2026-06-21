@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.viewmodels

import app.cash.turbine.test
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
import com.schedulersystems.scheduler.models.ui.AuthEvent
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
import org.junit.Before
import org.junit.Test

class AuthViewModelSignUpTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk()
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `SignUpWithEmail success navigates home and clears loading`() = runTest {
        val user = User("u1", "new@test.com", null, "New", Role.EMPLOYEE, false, null)
        coEvery { authRepository.signUpWithEmail("new@test.com", "pw123456") } returns Result.success(user)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.navigation.test {
            vm.onEvent(AuthEvent.SignUpWithEmail("new@test.com", "pw123456"))
            advanceUntilIdle()
            assertEquals("home", awaitItem())
        }
        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
        assertEquals("new@test.com", vm.uiState.value.user?.email)
    }

    @Test
    fun `SignUpWithEmail failure surfaces error and clears loading`() = runTest {
        coEvery { authRepository.signUpWithEmail(any(), any()) } returns
            Result.failure(Exception("Email is already registered"))
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SignUpWithEmail("dupe@test.com", "pw123456"))
        advanceUntilIdle()

        assertEquals("Email is already registered", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isLoading)
    }
}
