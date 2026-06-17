package com.schedulersystems.scheduler.ui.screens.notifications

import androidx.lifecycle.ViewModel
import com.schedulersystems.scheduler.models.domain.Notification
import com.schedulersystems.scheduler.models.domain.NotificationType
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import javax.inject.Inject

data class NotificationsState(
    val isLoading: Boolean = true,
    val notifications: List<Notification> = emptyList(),
    val unreadCount: Int = 0
)

@HiltViewModel
class NotificationsViewModel @Inject constructor() : ViewModel() {

    private val _state = MutableStateFlow(NotificationsState())
    val state: StateFlow<NotificationsState> = _state.asStateFlow()

    init {
        _state.update {
            it.copy(
                isLoading = false,
                notifications = sampleNotifications(),
                unreadCount = 2
            )
        }
    }

    fun markAsRead(notificationId: String) {
        _state.update { current ->
            val updated = current.notifications.map {
                if (it.id == notificationId) it.copy(isRead = true) else it
            }
            current.copy(
                notifications = updated,
                unreadCount = updated.count { !it.isRead }
            )
        }
    }

    private fun sampleNotifications(): List<Notification> = listOf(
        Notification(
            id = "1",
            isRead = false,
            fromUser = "system",
            toUser = null,
            content = "Your schedule for next week has been published",
            type = NotificationType.SYSTEM,
            chatRefId = null,
            timeCreated = java.time.Instant.now().minus(java.time.Duration.ofHours(2))
        ),
        Notification(
            id = "2",
            isRead = false,
            fromUser = "John",
            toUser = null,
            content = "You have a new schedule request from John Doe",
            type = NotificationType.SCHEDULE_REQUEST,
            chatRefId = null,
            timeCreated = java.time.Instant.now().minus(java.time.Duration.ofHours(5))
        ),
        Notification(
            id = "3",
            isRead = true,
            fromUser = "Team Alpha",
            toUser = null,
            content = "New message in Team Alpha chat",
            type = NotificationType.CHAT_MESSAGE,
            chatRefId = "1",
            timeCreated = java.time.Instant.now().minus(java.time.Duration.ofDays(1))
        )
    )
}
