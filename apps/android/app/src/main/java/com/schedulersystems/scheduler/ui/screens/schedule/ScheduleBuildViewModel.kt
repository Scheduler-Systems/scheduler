package com.schedulersystems.scheduler.ui.screens.schedule

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

/** Grid is `[station][day][shift]` of assigned employee names ("" = empty cell). */
data class ScheduleBuildState(
    val isLoading: Boolean = false,
    val grid: List<List<List<String>>> = emptyList(),
    val built: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class ScheduleBuildViewModel @Inject constructor(
    private val repository: ScheduleRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ScheduleBuildState())
    val state: StateFlow<ScheduleBuildState> = _state.asStateFlow()

    /** Loads the most recently built grid, if any, so a returning manager sees it. */
    fun load(scheduleId: String) {
        viewModelScope.launch {
            val latest = repository.getLatestBuiltSchedule(scheduleId)
            if (latest != null && latest.isNotEmpty()) {
                _state.update { it.copy(grid = latest, built = true) }
            }
        }
    }

    /** Runs the assignment algorithm and persists the grid via the API. */
    fun build(scheduleId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            repository.buildAndSaveSchedule(scheduleId).fold(
                onSuccess = { grid ->
                    _state.update { it.copy(isLoading = false, grid = grid, built = true) }
                },
                onFailure = { e ->
                    _state.update { it.copy(isLoading = false, error = e.message ?: "Build failed") }
                }
            )
        }
    }
}
