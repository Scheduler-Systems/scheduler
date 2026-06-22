package com.schedulersystems.scheduler.ui.screens.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.dto.UpsertRoleRequestDto
import com.schedulersystems.scheduler.data.network.dto.roleStructFor
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ChooseRoleState(
    val isSaving: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null
)

// Auth onboarding step 2: persist the chosen role (PUT /users/{uid}/role). On success the
// screen goes home. Server computes the role string from the RoleStruct.
@HiltViewModel
class ChooseRoleViewModel @Inject constructor(
    private val api: SchedulerApi,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ChooseRoleState())
    val state: StateFlow<ChooseRoleState> = _state.asStateFlow()

    fun saveRole(isManager: Boolean) {
        viewModelScope.launch {
            _state.update { it.copy(isSaving = true, error = null) }
            val user = authRepository.currentUser.first()
            val uid = user?.id
            if (uid == null) {
                _state.update { it.copy(isSaving = false, isSaved = true) }
                return@launch
            }
            try {
                val response = api.service.upsertRole(
                    uid, uid, UpsertRoleRequestDto(user.email ?: "", roleStructFor(isManager))
                )
                if (response.isSuccessful) {
                    _state.update { it.copy(isSaving = false, isSaved = true) }
                } else {
                    _state.update { it.copy(isSaving = false, error = "Failed to save role: ${response.code()}") }
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSaving = false, error = e.message ?: "Failed to save role") }
            }
        }
    }
}
