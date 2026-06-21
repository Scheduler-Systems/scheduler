package com.schedulersystems.scheduler.viewmodels

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.ui.AuthEvent
import com.schedulersystems.scheduler.models.ui.AuthUiState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class AuthViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    private val _navigation = MutableSharedFlow<String>()
    val navigation: SharedFlow<String> = _navigation.asSharedFlow()

    private var pendingVerificationId: String? = null

    init {
        observeAuthState()
    }

    private fun observeAuthState() {
        viewModelScope.launch {
            authRepository.isAuthenticated.collect { isAuthenticated ->
                _uiState.update { it.copy(isAuthenticated = isAuthenticated) }
            }
        }
        viewModelScope.launch {
            authRepository.currentUser.collect { user ->
                _uiState.update { it.copy(user = user) }
            }
        }
    }

    fun onEvent(event: AuthEvent) {
        when (event) {
            is AuthEvent.EmailChanged -> {
                _uiState.update { it.copy(email = event.email) }
            }
            is AuthEvent.PasswordChanged -> {
                _uiState.update { it.copy(password = event.password) }
            }
            is AuthEvent.PhoneChanged -> {
                _uiState.update { it.copy(phoneNumber = event.phone) }
            }
            is AuthEvent.SmsCodeChanged -> {
                _uiState.update { it.copy(smsCode = event.code) }
            }
            is AuthEvent.SignInWithEmail -> {
                signInWithEmail(event.email, event.password)
            }
            is AuthEvent.SignUpWithEmail -> {
                signUpWithEmail(event.email, event.password)
            }
            is AuthEvent.SendPhoneVerification -> {
                sendPhoneVerification(event.phoneNumber)
            }
            is AuthEvent.VerifyPhoneCode -> {
                verifyPhoneCode(event.code)
            }
            is AuthEvent.SignInWithGoogle -> {
                // Handled by Activity Result API
            }
            is AuthEvent.SignInWithApple -> {
                // Handled by Activity Result API
            }
            is AuthEvent.SignOut -> {
                signOut()
            }
            is AuthEvent.ClearError -> {
                _uiState.update { it.copy(error = null) }
            }
            is AuthEvent.ResetPassword -> {
                // Navigation-only event; the password-reset screen handles SendPasswordReset.
            }
            is AuthEvent.SendPasswordReset -> {
                sendPasswordReset(event.email)
            }
            is AuthEvent.SendEmailVerification -> {
                sendEmailVerification()
            }
            is AuthEvent.CheckEmailVerified -> {
                checkEmailVerified()
            }
        }
    }

    private fun sendEmailVerification() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null, emailVerificationSent = false) }
            val result = authRepository.sendEmailVerification()
            result.fold(
                onSuccess = {
                    _uiState.update { it.copy(isLoading = false, emailVerificationSent = true) }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun checkEmailVerified() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.reloadAndCheckEmailVerified()
            result.fold(
                onSuccess = { verified ->
                    if (verified) {
                        _uiState.update { it.copy(isLoading = false) }
                        _navigation.emit("home")
                    } else {
                        _uiState.update { it.copy(isLoading = false, error = "Email is not verified") }
                    }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun sendPasswordReset(email: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null, passwordResetSent = false) }
            val result = authRepository.sendPasswordResetEmail(email)
            result.fold(
                onSuccess = {
                    _uiState.update { it.copy(isLoading = false, passwordResetSent = true) }
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun signInWithEmail(email: String, password: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.signInWithEmail(email, password)
            result.fold(
                onSuccess = { user ->
                    _uiState.update { it.copy(isLoading = false, user = user) }
                    _navigation.emit("home")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun signUpWithEmail(email: String, password: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.signUpWithEmail(email, password)
            result.fold(
                onSuccess = { user ->
                    _uiState.update { it.copy(isLoading = false, user = user) }
                    _navigation.emit("home")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun sendPhoneVerification(phoneNumber: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.signInWithPhone(phoneNumber)
            result.fold(
                onSuccess = { verificationId ->
                    pendingVerificationId = verificationId
                    _uiState.update { 
                        it.copy(
                            isLoading = false, 
                            verificationId = verificationId,
                            isCodeSent = true
                        )
                    }
                    _navigation.emit("phoneCode")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun verifyPhoneCode(code: String) {
        viewModelScope.launch {
            val verificationId = pendingVerificationId ?: _uiState.value.verificationId
            if (verificationId == null) {
                _uiState.update { it.copy(error = "Verification ID not found") }
                return@launch
            }
            
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.verifyPhoneCode(verificationId, code)
            result.fold(
                onSuccess = { user ->
                    _uiState.update { it.copy(isLoading = false, user = user) }
                    _navigation.emit("home")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    fun onGoogleSignInResult(idToken: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.signInWithGoogle(idToken)
            result.fold(
                onSuccess = { user ->
                    _uiState.update { it.copy(isLoading = false, user = user) }
                    _navigation.emit("home")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    fun onAppleSignInResult(identityToken: String) {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, error = null) }
            val result = authRepository.signInWithApple(identityToken)
            result.fold(
                onSuccess = { user ->
                    _uiState.update { it.copy(isLoading = false, user = user) }
                    _navigation.emit("home")
                },
                onFailure = { error ->
                    _uiState.update { it.copy(isLoading = false, error = error.message) }
                }
            )
        }
    }

    private fun signOut() {
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true) }
            authRepository.signOut()
            _uiState.update { 
                AuthUiState() 
            }
        }
    }
}
