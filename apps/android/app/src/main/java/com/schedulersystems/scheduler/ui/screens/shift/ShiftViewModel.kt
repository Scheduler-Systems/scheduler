package com.schedulersystems.scheduler.ui.screens.shift

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.ShiftRow
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ShiftState(
    val isLoading: Boolean = true,
    val shiftRows: List<ShiftRow> = emptyList(),
    val error: String? = null
)

@HiltViewModel
class ShiftViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ShiftState())
    val state: StateFlow<ShiftState> = _state.asStateFlow()

    fun loadShifts(scheduleId: String, weekStart: String?) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }

            val schedule = scheduleRepository.getScheduleById(scheduleId)
            if (schedule != null) {
                _state.update {
                    it.copy(
                        isLoading = false,
                        shiftRows = schedule.nextSchedule
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
