package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.time.Instant
import javax.inject.Inject

data class NewScheduleState(
    val name: String = "",
    val isCreating: Boolean = false,
    val created: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class NewScheduleViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(NewScheduleState())
    val state: StateFlow<NewScheduleState> = _state.asStateFlow()

    fun setName(name: String) {
        _state.update { it.copy(name = name) }
    }

    fun create() {
        val name = _state.value.name.trim()
        if (name.isEmpty()) {
            _state.update { it.copy(error = "Name is required") }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(isCreating = true, error = null) }
            // tenantId is derived server-side from the path/token; the body value is
            // ignored, so "" is fine. Settings/shifts are configured later (schedule-build).
            val schedule = Schedule(
                id = "",
                name = name,
                tenantId = "",
                employees = emptyList(),
                currentPriorities = emptyList(),
                settings = ScheduleSettings(
                    submissionDeadline = null,
                    enabledShifts = EnabledShifts(mornings = false, afternoons = false, evenings = false),
                    timezone = "UTC"
                ),
                nextSchedule = emptyList(),
                createdAt = Instant.now(),
                updatedAt = Instant.now()
            )
            val result = scheduleRepository.createSchedule(schedule)
            result.fold(
                onSuccess = { _state.update { it.copy(isCreating = false, created = true) } },
                onFailure = { ex -> _state.update { it.copy(isCreating = false, error = ex.message ?: "Failed to create schedule") } }
            )
        }
    }
}
