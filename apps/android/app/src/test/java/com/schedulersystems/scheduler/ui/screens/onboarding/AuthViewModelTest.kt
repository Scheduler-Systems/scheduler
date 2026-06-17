@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.onboarding

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
import com.schedulersystems.scheduler.models.ui.AuthEvent
import com.schedulersystems.scheduler.viewmodels.AuthViewModel
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class AuthViewModelTest {

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
    fun `should observe auth state on init`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(user)
        every { authRepository.isAuthenticated } returns flowOf(true)

        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        assertTrue(vm.uiState.value.isAuthenticated)
        assertNotNull(vm.uiState.value.user)
        assertEquals("Test", vm.uiState.value.user?.displayName)
    }

    @Test
    fun `should update email on EmailChanged event`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)

        val vm = AuthViewModel(authRepository)

        vm.onEvent(AuthEvent.EmailChanged("test@example.com"))

        assertEquals("test@example.com", vm.uiState.value.email)
    }

    @Test
    fun `should update password on PasswordChanged event`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)

        val vm = AuthViewModel(authRepository)

        vm.onEvent(AuthEvent.PasswordChanged("secret123"))

        assertEquals("secret123", vm.uiState.value.password)
    }

    @Test
    fun `should sign in successfully`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithEmail("test@test.com", "pass") } returns Result.success(user)

        val vm = AuthViewModel(authRepository)
        vm.onEvent(AuthEvent.EmailChanged("test@test.com"))
        vm.onEvent(AuthEvent.PasswordChanged("pass"))
        vm.onEvent(AuthEvent.SignInWithEmail("test@test.com", "pass"))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `should show error on sign in failure`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithEmail("bad@test.com", "wrong") } returns
            Result.failure(Exception("Invalid credentials"))

        val vm = AuthViewModel(authRepository)
        vm.onEvent(AuthEvent.SignInWithEmail("bad@test.com", "wrong"))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertEquals("Invalid credentials", vm.uiState.value.error)
    }

    @Test
    fun `should clear error on ClearError event`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)

        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.ClearError)

        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `should sign out successfully`() = runTest {
        val user = User("user-1", "test@test.com", null, "Test", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(user)
        every { authRepository.isAuthenticated } returns flowOf(true)
        coEvery { authRepository.signOut() } returns Result.success(Unit)

        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.SignOut)
        advanceUntilIdle()

        assertNull(vm.uiState.value.user)
    }

    @Test
    fun `should update phone number`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)

        val vm = AuthViewModel(authRepository)

        vm.onEvent(AuthEvent.PhoneChanged("+1234567890"))

        assertEquals("+1234567890", vm.uiState.value.phoneNumber)
    }

    @Test
    fun `should handle google sign in result`() = runTest {
        val user = User("user-1", "google@test.com", null, "Google User", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithGoogle("google-token") } returns Result.success(user)

        val vm = AuthViewModel(authRepository)
        vm.onGoogleSignInResult("google-token")
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `should handle apple sign in result`() = runTest {
        val user = User("user-1", "apple@test.com", null, "Apple User", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithApple("apple-token") } returns Result.success(user)

        val vm = AuthViewModel(authRepository)
        vm.onAppleSignInResult("apple-token")
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
    }

    @Test
    fun `should send phone verification successfully`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithPhone("+1234567890") } returns Result.success("verification-id-123")

        val vm = AuthViewModel(authRepository)
        vm.onEvent(AuthEvent.SendPhoneVerification("+1234567890"))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertEquals("verification-id-123", vm.uiState.value.verificationId)
        assertTrue(vm.uiState.value.isCodeSent)
    }

    @Test
    fun `should verify phone code successfully`() = runTest {
        val user = User("user-1", null, "+1234567890", null, Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signInWithPhone("+1234567890") } returns Result.success("verification-id-123")
        coEvery { authRepository.verifyPhoneCode("verification-id-123", "123456") } returns Result.success(user)

        val vm = AuthViewModel(authRepository)
        vm.onEvent(AuthEvent.SendPhoneVerification("+1234567890"))
        advanceUntilIdle()

        vm.onEvent(AuthEvent.VerifyPhoneCode("123456"))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `should show error on verify phone code failure`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.verifyPhoneCode("bad-id", "123456") } returns
            Result.failure(Exception("Invalid verification"))

        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        vm.onEvent(AuthEvent.VerifyPhoneCode("123456"))
        advanceUntilIdle()

        assertEquals("Verification ID not found", vm.uiState.value.error)
    }

    @Test
    fun `should handle sign up successfully`() = runTest {
        val user = User("user-1", "new@test.com", null, "New User", Role.EMPLOYEE, false, null)
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)
        coEvery { authRepository.signUpWithEmail("new@test.com", "pass123") } returns Result.success(user)

        val vm = AuthViewModel(authRepository)
        vm.onEvent(AuthEvent.SignUpWithEmail("new@test.com", "pass123"))
        advanceUntilIdle()

        assertFalse(vm.uiState.value.isLoading)
        assertNull(vm.uiState.value.error)
    }

    @Test
    fun `should start with default ui state`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)
        every { authRepository.isAuthenticated } returns flowOf(false)

        val vm = AuthViewModel(authRepository)
        advanceUntilIdle()

        assertEquals("", vm.uiState.value.email)
        assertEquals("", vm.uiState.value.password)
        assertEquals("", vm.uiState.value.phoneNumber)
        assertFalse(vm.uiState.value.isAuthenticated)
    }
}
