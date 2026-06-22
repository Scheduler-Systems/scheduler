@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.viewmodels

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.User
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

class AuthViewModelPhoneTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk()
        // VM observes these in init; the phone flow drives auth via verifyPhoneCode instead.
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `SendPhoneVerification success flips isCodeSent and stores verificationId`() = runTest {
        coEvery { authRepository.signInWithPhone("+15555550100") } returns Result.success("vid-123")
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendPhoneVerification("+15555550100"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue("code-entry should show after a successful send", state.isCodeSent)
        assertEquals("vid-123", state.verificationId)
        assertFalse(state.isLoading)
        assertNull(state.error)
        coVerify(exactly = 1) { authRepository.signInWithPhone("+15555550100") }
    }

    @Test
    fun `SendPhoneVerification failure surfaces error and stays on phone entry`() = runTest {
        coEvery { authRepository.signInWithPhone(any()) } returns
            Result.failure(Exception("Invalid phone number"))
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendPhoneVerification("+1bad"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertFalse("must not advance to code entry on failure", state.isCodeSent)
        assertFalse(state.isLoading)
        assertEquals("Invalid phone number", state.error)
    }

    @Test
    fun `VerifyPhoneCode success uses the stored verificationId and clears loading`() = runTest {
        val user = User(
            id = "u1", email = null, phone = "+15555550100", displayName = null,
            role = null, isPremium = false, tenantId = "u1"
        )
        coEvery { authRepository.signInWithPhone("+15555550100") } returns Result.success("vid-123")
        coEvery { authRepository.verifyPhoneCode("vid-123", "654321") } returns Result.success(user)
        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SendPhoneVerification("+15555550100"))
        advanceUntilIdle()
        vm.onEvent(AuthEvent.VerifyPhoneCode("654321"))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(user, state.user)
        assertFalse(state.isLoading)
        assertNull(state.error)
        // The verificationId from the send step must reach verify (single-screen state-sharing).
        coVerify(exactly = 1) { authRepository.verifyPhoneCode("vid-123", "654321") }
    }
}
