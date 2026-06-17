package com.schedulersystems.scheduler.models.ui

import com.schedulersystems.scheduler.models.domain.User

data class AuthUiState(
    val isLoading: Boolean = false,
    val isAuthenticated: Boolean = false,
    val user: User? = null,
    val error: String? = null,
    val email: String = "",
    val password: String = "",
    val phoneNumber: String = "",
    val verificationId: String? = null,
    val smsCode: String = "",
    val isCodeSent: Boolean = false
)

sealed class AuthEvent {
    data class EmailChanged(val email: String) : AuthEvent()
    data class PasswordChanged(val password: String) : AuthEvent()
    data class PhoneChanged(val phone: String) : AuthEvent()
    data class SmsCodeChanged(val code: String) : AuthEvent()
    data class SignInWithEmail(val email: String, val password: String) : AuthEvent()
    data class SignUpWithEmail(val email: String, val password: String) : AuthEvent()
    data class SendPhoneVerification(val phoneNumber: String) : AuthEvent()
    data class VerifyPhoneCode(val code: String) : AuthEvent()
    data object SignInWithGoogle : AuthEvent()
    data object SignInWithApple : AuthEvent()
    data object SignOut : AuthEvent()
    data object ClearError : AuthEvent()
    data object ResetPassword : AuthEvent()
}

sealed class AuthNavigation {
    data object ToHome : AuthNavigation()
    data object ToPhoneCode : AuthNavigation()
    data object ToEmailLogin : AuthNavigation()
    data object ToSignUp : AuthNavigation()
    data class Error(val message: String) : AuthNavigation()
}
