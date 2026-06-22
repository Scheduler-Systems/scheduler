package com.schedulersystems.scheduler.ui.screens.requests

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.ScheduleRequest
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ScheduleRequestsState(
    val isLoading: Boolean = true,
    val requests: List<ScheduleRequest> = emptyList(),
    val error: String? = null
)

@HiltViewModel
class ScheduleRequestsViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ScheduleRequestsState())
    val state: StateFlow<ScheduleRequestsState> = _state.asStateFlow()

    fun load(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val requests = scheduleRepository.getInvitations(scheduleId)
            _state.update { it.copy(isLoading = false, requests = requests, error = null) }
        }
    }
}
