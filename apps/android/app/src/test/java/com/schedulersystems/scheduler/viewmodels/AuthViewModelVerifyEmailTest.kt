@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.viewmodels

import app.cash.turbine.test
import com.schedulersystems.scheduler.data.repositories.AuthRepository
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
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class AuthViewModelVerifyEmailTest {

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
    fun `CheckEmailVerified navigates home when verified`() = runTest {
        coEvery { authRepository.reloadAndCheckEmailVerified() } returns Result.success(true)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.navigation.test {
            vm.onEvent(AuthEvent.CheckEmailVerified)
            advanceUntilIdle()
            assertEquals("home", awaitItem())
        }
        assertFalse(vm.uiState.value.isLoading)
    }

    @Test
    fun `CheckEmailVerified sets error when not verified`() = runTest {
        coEvery { authRepository.reloadAndCheckEmailVerified() } returns Result.success(false)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.CheckEmailVerified)
        advanceUntilIdle()

        assertEquals("Email is not verified", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isLoading)
    }

    @Test
    fun `SendEmailVerification success sets emailVerificationSent`() = runTest {
        coEvery { authRepository.sendEmailVerification() } returns Result.success(Unit)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendEmailVerification)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.emailVerificationSent)
        assertFalse(vm.uiState.value.isLoading)
    }
}
