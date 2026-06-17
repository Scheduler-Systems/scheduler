package com.schedulersystems.scheduler.ui.screens.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.SubmissionDeadline
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class SettingsState(
    val isLoading: Boolean = true,
    val scheduleName: String = "",
    val enabledShifts: EnabledShifts = EnabledShifts(false, false, false),
    val submissionDeadlineEnabled: Boolean = false,
    val deadlineDay: String = "Sunday",
    val timezone: String = "UTC",
    val isSaving: Boolean = false,
    val isSaved: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class ScheduleSettingsViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(SettingsState())
    val state: StateFlow<SettingsState> = _state.asStateFlow()

    fun loadSettings(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                _state.update {
                    it.copy(
                        isLoading = false,
                        scheduleName = schedule.name,
                        enabledShifts = schedule.settings.enabledShifts,
                        submissionDeadlineEnabled = schedule.settings.submissionDeadline?.enabled ?: false,
                        timezone = schedule.settings.timezone
                    )
                }
            } else {
                _state.update { it.copy(isLoading = false, error = "Schedule not found") }
            }
        }
    }

    fun toggleMorning(enabled: Boolean) {
        _state.update { it.copy(enabledShifts = it.enabledShifts.copy(mornings = enabled)) }
    }

    fun toggleAfternoon(enabled: Boolean) {
        _state.update { it.copy(enabledShifts = it.enabledShifts.copy(afternoons = enabled)) }
    }

    fun toggleEvening(enabled: Boolean) {
        _state.update { it.copy(enabledShifts = it.enabledShifts.copy(evenings = enabled)) }
    }

    fun toggleDeadline(enabled: Boolean) {
        _state.update { it.copy(submissionDeadlineEnabled = enabled) }
    }

    fun setDeadlineDay(day: String) {
        _state.update { it.copy(deadlineDay = day) }
    }

    fun setTimezone(tz: String) {
        _state.update { it.copy(timezone = tz) }
    }

    fun saveSettings(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isSaving = true, error = null) }
            val current = _state.value
            val deadline = if (current.submissionDeadlineEnabled) {
                SubmissionDeadline(
                    enabled = true,
                    deadline = java.time.Instant.now().plus(java.time.Duration.ofDays(7))
                )
            } else {
                SubmissionDeadline(enabled = false, deadline = null)
            }
            val settings = ScheduleSettings(
                submissionDeadline = deadline,
                enabledShifts = current.enabledShifts,
                timezone = current.timezone
            )
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                val updated = schedule.copy(settings = settings)
                val result = scheduleRepository.updateSchedule(updated)
                result.fold(
                    onSuccess = { _state.update { it.copy(isSaving = false, isSaved = true) } },
                    onFailure = { ex -> _state.update { it.copy(isSaving = false, error = ex.message) } }
                )
            } else {
                _state.update { it.copy(isSaving = false, error = "Schedule not found") }
            }
        }
    }
}
