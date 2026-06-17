package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.Role
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ScheduleDetailState(
    val isLoading: Boolean = true,
    val schedule: Schedule? = null,
    val userRole: Role? = null,
    val scheduleCount: Int = 0,
    val attendancePercentage: Double = 0.0,
    val error: String? = null
)

@HiltViewModel
class ScheduleDetailViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ScheduleDetailState())
    val state: StateFlow<ScheduleDetailState> = _state.asStateFlow()

    fun loadSchedule(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }

            val userRole = authRepository.currentUser.first()?.role

            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                _state.update {
                    it.copy(
                        isLoading = false,
                        schedule = schedule,
                        userRole = userRole,
                        scheduleCount = schedule.nextSchedule.size
                    )
                }
            } else {
                _state.update {
                    it.copy(
                        isLoading = false,
                        error = "Schedule not found"
                    )
                }
            }
        }
    }
}
