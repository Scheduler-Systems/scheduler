package com.schedulersystems.scheduler.ui.screens.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.ui.ChatItem
import com.schedulersystems.scheduler.models.ui.ChatUiState
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class ChatViewModel @Inject constructor(
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    init {
        loadChats()
    }

    fun loadChats() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            _state.update {
                it.copy(
                    isLoading = false,
                    chats = sampleChats()
                )
            }
        }
    }

    private fun sampleChats(): List<ChatItem> = listOf(
        ChatItem(id = "1", name = "Team Alpha", lastMessage = "Meeting at 3pm?", timestamp = System.currentTimeMillis() - 3600000, unreadCount = 2),
        ChatItem(id = "2", name = "John Doe", lastMessage = "Thanks!", timestamp = System.currentTimeMillis() - 86400000, unreadCount = 0),
        ChatItem(id = "3", name = "Support", lastMessage = "How can we help?", timestamp = System.currentTimeMillis() - 7200000, unreadCount = 1)
    )
}
