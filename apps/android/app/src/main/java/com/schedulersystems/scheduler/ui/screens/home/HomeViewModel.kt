package com.schedulersystems.scheduler.ui.screens.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class HomeState(
    val isLoading: Boolean = true,
    val displayName: String? = null,
    val userRole: Role? = null,
    val isPremium: Boolean = false,
    val notificationCount: Int = 0,
    val schedulesInvolvedCount: Int = 0,
    val isUpdateAvailable: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(HomeState())
    val state: StateFlow<HomeState> = _state.asStateFlow()

    init {
        initialize()
    }

    private fun initialize() {
        viewModelScope.launch {
            authRepository.currentUser.collect { user ->
                _state.update { currentState ->
                    currentState.copy(
                        isLoading = false,
                        displayName = user?.displayName,
                        userRole = user?.role,
                        isPremium = user?.isPremium ?: false
                    )
                }
            }
        }
    }

    fun refreshUser() {
        // TODO: Implement refresh
    }
}
