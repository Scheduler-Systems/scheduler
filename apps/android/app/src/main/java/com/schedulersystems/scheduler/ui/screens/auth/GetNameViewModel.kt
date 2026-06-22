package com.schedulersystems.scheduler.ui.screens.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.dto.UpsertProfileRequestDto
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class GetNameState(
    val isSaving: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null
)

// Auth onboarding step 1: persist display_name (PUT /users/{uid}). On success the screen
// continues to choose-role. tenant = own uid (single-user tenancy; the API enforces
// uid == actor for own-profile writes).
@HiltViewModel
class GetNameViewModel @Inject constructor(
    private val api: SchedulerApi,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(GetNameState())
    val state: StateFlow<GetNameState> = _state.asStateFlow()

    fun saveName(name: String) {
        viewModelScope.launch {
            _state.update { it.copy(isSaving = true, error = null) }
            val user = authRepository.currentUser.first()
            val uid = user?.id
            if (uid == null) {
                _state.update { it.copy(isSaving = false, isSaved = true) }
                return@launch
            }
            try {
                val response = api.service.upsertProfile(
                    uid, uid, UpsertProfileRequestDto(user.email ?: "", name)
                )
                if (response.isSuccessful) {
                    _state.update { it.copy(isSaving = false, isSaved = true) }
                } else {
                    _state.update { it.copy(isSaving = false, error = "Failed to save name: ${response.code()}") }
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSaving = false, error = e.message ?: "Failed to save name") }
            }
        }
    }
}
