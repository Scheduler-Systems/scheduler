@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.viewmodels

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.ui.AuthEvent
import io.mockk.coEvery
import io.mockk.coVerify
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

class AuthViewModelPasswordResetTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk()
        // VM observes these in init; password reset doesn't depend on them.
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `SendPasswordReset success sets passwordResetSent and clears loading`() = runTest {
        coEvery { authRepository.sendPasswordResetEmail("user@test.com") } returns Result.success(Unit)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendPasswordReset("user@test.com"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue("reset flag should be set on success", state.passwordResetSent)
        assertFalse(state.isLoading)
        assertNull(state.error)
        coVerify(exactly = 1) { authRepository.sendPasswordResetEmail("user@test.com") }
    }

    @Test
    fun `SendPasswordReset failure sets error and leaves passwordResetSent false`() = runTest {
        coEvery { authRepository.sendPasswordResetEmail(any()) } returns
            Result.failure(Exception("No account found"))
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendPasswordReset("missing@test.com"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse(state.passwordResetSent)
        assertFalse(state.isLoading)
        assertEquals("No account found", state.error)
    }
}
