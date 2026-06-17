package com.schedulersystems.scheduler.ui.screens.geminiai

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class GeminiState(
    val prompt: String = "",
    val response: String = "",
    val isLoading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class GeminiViewModel @Inject constructor() : ViewModel() {

    private val _state = MutableStateFlow(GeminiState())
    val state: StateFlow<GeminiState> = _state.asStateFlow()

    fun setPrompt(prompt: String) {
        _state.update { it.copy(prompt = prompt) }
    }

    fun generate() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            kotlinx.coroutines.delay(2000)
            _state.update {
                it.copy(
                    isLoading = false,
                    response = "AI scheduling assistant response for: \"${it.prompt}\"\n\nBased on your schedule data, I recommend optimizing the morning shift coverage..."
                )
            }
        }
    }
}
