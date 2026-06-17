package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Schedule
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ScheduleListState(
    val isLoading: Boolean = true,
    val schedules: List<Schedule> = emptyList(),
    val error: String? = null,
    val initCompleted: Boolean = false
)

@HiltViewModel
class ScheduleListViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ScheduleListState())
    val state: StateFlow<ScheduleListState> = _state.asStateFlow()

    init {
        loadSchedules()
    }

    private fun loadSchedules() {
        viewModelScope.launch {
            val userId = authRepository.currentUser.first()?.id
            if (userId == null) {
                _state.update { it.copy(isLoading = false, initCompleted = true) }
                return@launch
            }

            scheduleRepository.getSchedulesForUser(userId).collect { schedules ->
                _state.update { currentState ->
                    currentState.copy(
                        isLoading = false,
                        schedules = schedules,
                        initCompleted = true
                    )
                }
            }
        }
    }

    fun refresh() {
        _state.update { it.copy(isLoading = true) }
        loadSchedules()
    }
}
