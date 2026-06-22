package com.schedulersystems.scheduler.ui.screens.priority

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class CurrentPrioritiesState(
    val isLoading: Boolean = true,
    val priorities: List<String> = emptyList(),
    val error: String? = null
)

// Read-only view of a schedule's current priority standings (current_priorities from the
// Go API). Distinct from PrioritiesViewModel (which submits) — this only loads + displays.
@HiltViewModel
class CurrentPrioritiesViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(CurrentPrioritiesState())
    val state: StateFlow<CurrentPrioritiesState> = _state.asStateFlow()

    fun loadCurrentPriorities(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                _state.update { it.copy(isLoading = false, priorities = schedule.currentPriorities) }
            } else {
                _state.update { it.copy(isLoading = false, error = "Schedule not found") }
            }
        }
    }
}
