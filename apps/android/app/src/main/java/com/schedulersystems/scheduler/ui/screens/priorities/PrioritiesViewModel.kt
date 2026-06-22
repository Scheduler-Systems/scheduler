package com.schedulersystems.scheduler.ui.screens.priorities

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class PrioritiesState(
    val isLoading: Boolean = true,
    val priorities: List<String> = emptyList(),
    val submittedPriorities: List<Boolean> = emptyList(),
    val employees: List<String> = emptyList(),
    val isSubmitting: Boolean = false,
    val isSubmitted: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class PrioritiesViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(PrioritiesState())
    val state: StateFlow<PrioritiesState> = _state.asStateFlow()

    fun loadPriorities(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                val employees = schedule.employees.map { it.name }
                _state.update {
                    it.copy(
                        isLoading = false,
                        priorities = schedule.currentPriorities,
                        submittedPriorities = List(schedule.currentPriorities.size) { false },
                        employees = employees
                    )
                }
            } else {
                _state.update { it.copy(isLoading = false, error = "Schedule not found") }
            }
        }
    }

    fun togglePriority(index: Int) {
        _state.update {
            it.copy(
                submittedPriorities = it.submittedPriorities.toMutableList().apply { set(index, !get(index)) }
            )
        }
    }

    fun submitPriorities(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isSubmitting = true, error = null) }
            val current = _state.value
            val selected = current.priorities.filterIndexed { i, _ ->
                current.submittedPriorities.getOrElse(i) { false }
            }
            val availability = mapOf<String, Any>(
                "priorities" to current.priorities,
                "selected" to selected
            )
            scheduleRepository.submitAvailability(scheduleId, availability).fold(
                onSuccess = { _state.update { it.copy(isSubmitting = false, isSubmitted = true) } },
                onFailure = { e ->
                    _state.update { it.copy(isSubmitting = false, error = e.message ?: "Failed to submit priorities") }
                }
            )
        }
    }
}
