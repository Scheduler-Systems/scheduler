package com.schedulersystems.scheduler.models.ui

import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthUiStateTest {

    @Test
    fun `AuthUiState defaults`() {
        val state = AuthUiState()
        assertFalse(state.isLoading)
        assertFalse(state.isAuthenticated)
        assertNull(state.user)
        assertNull(state.error)
        assertEquals("", state.email)
        assertEquals("", state.password)
        assertEquals("", state.phoneNumber)
        assertNull(state.verificationId)
        assertEquals("", state.smsCode)
        assertFalse(state.isCodeSent)
    }

    @Test
    fun `AuthUiState with values`() {
        val user = User("u1", "test@test.com", null, "Alice", Role.EMPLOYER, true, "t1")
        val state = AuthUiState(
            isLoading = true,
            isAuthenticated = true,
            user = user,
            error = "Auth error",
            email = "test@test.com",
            password = "pass123",
            phoneNumber = "1234567890",
            verificationId = "verif-1",
            smsCode = "123456",
            isCodeSent = true
        )
        assertTrue(state.isLoading)
        assertTrue(state.isAuthenticated)
        assertEquals(user, state.user)
        assertEquals("Auth error", state.error)
        assertEquals("test@test.com", state.email)
        assertEquals("pass123", state.password)
        assertEquals("1234567890", state.phoneNumber)
        assertEquals("verif-1", state.verificationId)
        assertEquals("123456", state.smsCode)
        assertTrue(state.isCodeSent)
    }

    @Test
    fun `AuthEvent EmailChanged`() {
        val event = AuthEvent.EmailChanged("new@test.com")
        assertEquals("new@test.com", (event as AuthEvent.EmailChanged).email)
    }

    @Test
    fun `AuthEvent PasswordChanged`() {
        val event = AuthEvent.PasswordChanged("newpass")
        assertEquals("newpass", (event as AuthEvent.PasswordChanged).password)
    }

    @Test
    fun `AuthEvent PhoneChanged`() {
        val event = AuthEvent.PhoneChanged("9876543210")
        assertEquals("9876543210", (event as AuthEvent.PhoneChanged).phone)
    }

    @Test
    fun `AuthEvent SmsCodeChanged`() {
        val event = AuthEvent.SmsCodeChanged("654321")
        assertEquals("654321", (event as AuthEvent.SmsCodeChanged).code)
    }

    @Test
    fun `AuthEvent SignInWithEmail`() {
        val event = AuthEvent.SignInWithEmail("e@test.com", "pass")
        assertEquals("e@test.com", (event as AuthEvent.SignInWithEmail).email)
        assertEquals("pass", event.password)
    }

    @Test
    fun `AuthEvent SignUpWithEmail`() {
        val event = AuthEvent.SignUpWithEmail("e@test.com", "pass")
        assertEquals("e@test.com", (event as AuthEvent.SignUpWithEmail).email)
        assertEquals("pass", event.password)
    }

    @Test
    fun `AuthEvent SendPhoneVerification`() {
        val event = AuthEvent.SendPhoneVerification("1234567890")
        assertEquals("1234567890", (event as AuthEvent.SendPhoneVerification).phoneNumber)
    }

    @Test
    fun `AuthEvent VerifyPhoneCode`() {
        val event = AuthEvent.VerifyPhoneCode("123456")
        assertEquals("123456", (event as AuthEvent.VerifyPhoneCode).code)
    }

    @Test
    fun `AuthEvent singletons`() {
        assertEquals(AuthEvent.SignInWithGoogle, AuthEvent.SignInWithGoogle)
        assertEquals(AuthEvent.SignInWithApple, AuthEvent.SignInWithApple)
        assertEquals(AuthEvent.SignOut, AuthEvent.SignOut)
        assertEquals(AuthEvent.ClearError, AuthEvent.ClearError)
        assertEquals(AuthEvent.ResetPassword, AuthEvent.ResetPassword)
    }

    @Test
    fun `AuthNavigation ToHome`() {
        assertEquals(AuthNavigation.ToHome, AuthNavigation.ToHome)
    }

    @Test
    fun `AuthNavigation ToPhoneCode`() {
        assertEquals(AuthNavigation.ToPhoneCode, AuthNavigation.ToPhoneCode)
    }

    @Test
    fun `AuthNavigation ToEmailLogin`() {
        assertEquals(AuthNavigation.ToEmailLogin, AuthNavigation.ToEmailLogin)
    }

    @Test
    fun `AuthNavigation ToSignUp`() {
        assertEquals(AuthNavigation.ToSignUp, AuthNavigation.ToSignUp)
    }

    @Test
    fun `AuthNavigation Error`() {
        val nav = AuthNavigation.Error("Something went wrong")
        assertEquals("Something went wrong", (nav as AuthNavigation.Error).message)
    }
}
