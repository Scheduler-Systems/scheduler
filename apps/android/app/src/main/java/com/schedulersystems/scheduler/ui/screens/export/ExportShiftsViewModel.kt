package com.schedulersystems.scheduler.ui.screens.export

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

data class ExportState(
    val isLoading: Boolean = true,
    val scheduleName: String = "",
    val isExporting: Boolean = false,
    val isExported: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class ExportShiftsViewModel @Inject constructor(
    private val scheduleRepository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ExportState())
    val state: StateFlow<ExportState> = _state.asStateFlow()

    fun loadSchedule(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val schedule = scheduleRepository.getScheduleById(scheduleId)
            _state.update {
                it.copy(
                    isLoading = false,
                    scheduleName = schedule?.name ?: ""
                )
            }
        }
    }

    fun exportToGoogleCalendar(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isExporting = true) }
            kotlinx.coroutines.delay(1500)
            _state.update { it.copy(isExporting = false, isExported = true) }
        }
    }
}
