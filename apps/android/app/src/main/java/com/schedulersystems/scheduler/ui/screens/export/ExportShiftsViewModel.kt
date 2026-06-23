package com.schedulersystems.scheduler.ui.screens.export

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.domain.export.buildScheduleIcs
import com.schedulersystems.scheduler.domain.export.scheduleIcsFilename
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import dagger.hilt.android.lifecycle.HiltViewModel
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.LocalDate
import javax.inject.Inject

/**
 * Export Shifts: writes the built schedule grid to a real iCalendar (.ics) file and shares it
 * via the system share sheet — a credential-free calendar export (imports into Google Calendar
 * and every other calendar app). Self-sufficient: if no built schedule exists yet it builds one.
 */
@HiltViewModel
class ExportShiftsViewModel @Inject constructor(
    private val repository: ScheduleRepository,
    @ApplicationContext private val appContext: Context
) : ViewModel() {

    data class State(
        val isLoading: Boolean = false,
        val scheduleName: String = "",
        val enabledShifts: List<String> = emptyList(),
        val grid: List<List<List<String>>> = emptyList(),
        val isExporting: Boolean = false,
        val icsFile: File? = null,
        val eventCount: Int = 0,
        val error: String? = null
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    fun load(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val schedule = repository.getScheduleById(scheduleId)
                val name = schedule?.name ?: ""
                val shifts = schedule?.let { enabledShiftLabels(it.settings.enabledShifts) }
                    ?: listOf("Morning", "Afternoon", "Night")
                var grid = repository.getLatestBuiltSchedule(scheduleId)
                if (grid.isNullOrEmpty()) {
                    grid = repository.buildAndSaveSchedule(scheduleId).getOrNull()
                }
                _state.update {
                    it.copy(isLoading = false, scheduleName = name, enabledShifts = shifts, grid = grid ?: emptyList())
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.message ?: "Failed to load schedule") }
            }
        }
    }

    /** Generates the .ics for the current grid (anchored to this week) and writes it to a file. */
    fun export() {
        val s = _state.value
        viewModelScope.launch {
            _state.update { it.copy(isExporting = true, error = null) }
            try {
                val weekStart = LocalDate.now().toEpochDay()
                val ics = buildScheduleIcs(s.scheduleName, s.enabledShifts, s.grid, weekStart)
                val file = withContext(Dispatchers.IO) {
                    File(appContext.cacheDir, scheduleIcsFilename(s.scheduleName)).apply { writeText(ics) }
                }
                val events = Regex("BEGIN:VEVENT").findAll(ics).count()
                _state.update { it.copy(isExporting = false, icsFile = file, eventCount = events) }
            } catch (e: Exception) {
                _state.update { it.copy(isExporting = false, error = e.message ?: "Export failed") }
            }
        }
    }

    private fun enabledShiftLabels(es: EnabledShifts): List<String> = buildList {
        if (es.mornings) add("Morning")
        if (es.afternoons) add("Afternoon")
        if (es.evenings) add("Night")
    }.ifEmpty { listOf("Morning", "Afternoon", "Night") }
}
