package com.schedulersystems.scheduler.ui.screens.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ProfileState(
    val isLoading: Boolean = true,
    val displayName: String = "",
    val email: String? = null,
    val phone: String? = null,
    val role: String? = null,
    val isPremium: Boolean = false,
    val isEditing: Boolean = false,
    val editName: String = "",
    val isSaving: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class ProfileSettingsViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ProfileState())
    val state: StateFlow<ProfileState> = _state.asStateFlow()

    init {
        loadProfile()
    }

    fun loadProfile() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val user = authRepository.currentUser.first()
            _state.update {
                it.copy(
                    isLoading = false,
                    displayName = user?.displayName ?: "",
                    email = user?.email,
                    phone = user?.phone,
                    role = user?.role?.name,
                    isPremium = user?.isPremium ?: false
                )
            }
        }
    }

    fun startEditing() {
        _state.update { it.copy(isEditing = true, editName = it.displayName) }
    }

    fun cancelEditing() {
        _state.update { it.copy(isEditing = false, editName = "") }
    }

    fun setEditName(name: String) {
        _state.update { it.copy(editName = name) }
    }

    fun saveProfile() {
        viewModelScope.launch {
            _state.update { it.copy(isSaving = true) }
            val result = authRepository.updateUserProfile(_state.value.editName)
            result.fold(
                onSuccess = {
                    _state.update {
                        it.copy(
                            isSaving = false,
                            isSaved = true,
                            isEditing = false,
                            displayName = it.editName
                        )
                    }
                },
                onFailure = { ex -> _state.update { it.copy(isSaving = false, error = ex.message) } }
            )
        }
    }

    fun signOut() {
        viewModelScope.launch {
            authRepository.signOut()
        }
    }
}
