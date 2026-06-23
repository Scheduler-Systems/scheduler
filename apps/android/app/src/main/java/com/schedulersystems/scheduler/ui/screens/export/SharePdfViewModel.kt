package com.schedulersystems.scheduler.ui.screens.export

import android.content.Context
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.domain.export.buildSchedulePdfDoc
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
import javax.inject.Inject

/**
 * Share PDF: renders the latest built schedule grid into a real on-device PDF and
 * shares it via the system share sheet. Self-sufficient — if no built schedule
 * exists yet it builds one first, so there is always something real to export.
 */
@HiltViewModel
class SharePdfViewModel @Inject constructor(
    private val repository: ScheduleRepository,
    @ApplicationContext private val appContext: Context
) : ViewModel() {

    data class State(
        val isLoading: Boolean = false,
        val scheduleName: String = "",
        val enabledShifts: List<String> = emptyList(),
        val grid: List<List<List<String>>> = emptyList(),
        val isGenerating: Boolean = false,
        val pdfFile: File? = null,
        val pageCount: Int = 0,
        val error: String? = null
    )

    private val _state = MutableStateFlow(State())
    val state: StateFlow<State> = _state.asStateFlow()

    /** Loads the schedule + ensures a built grid exists (latest, else build one). */
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
                    it.copy(
                        isLoading = false,
                        scheduleName = name,
                        enabledShifts = shifts,
                        grid = grid ?: emptyList()
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.message ?: "Failed to load schedule") }
            }
        }
    }

    /** Renders the current grid to a real PDF file and counts its pages. */
    fun generate() {
        val s = _state.value
        viewModelScope.launch {
            _state.update { it.copy(isGenerating = true, error = null) }
            try {
                val doc = buildSchedulePdfDoc(
                    scheduleName = s.scheduleName,
                    enabledShifts = s.enabledShifts,
                    grid = s.grid
                )
                val rendered = withContext(Dispatchers.IO) { SchedulePdfRenderer.render(appContext, doc) }
                _state.update { it.copy(isGenerating = false, pdfFile = rendered.file, pageCount = rendered.pageCount) }
            } catch (e: Exception) {
                _state.update { it.copy(isGenerating = false, error = e.message ?: "PDF generation failed") }
            }
        }
    }

    private fun enabledShiftLabels(es: EnabledShifts): List<String> = buildList {
        if (es.mornings) add("Morning")
        if (es.afternoons) add("Afternoon")
        if (es.evenings) add("Night")
    }.ifEmpty { listOf("Morning", "Afternoon", "Night") }
}
