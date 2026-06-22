package com.schedulersystems.scheduler.ui.screens.notifications

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.dto.toDomain
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Notification
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class NotificationsState(
    val isLoading: Boolean = true,
    val notifications: List<Notification> = emptyList(),
    val unreadCount: Int = 0
)

// Loads the signed-in user's notification feed from the Go API (was hardcoded sample data).
@HiltViewModel
class NotificationsViewModel @Inject constructor(
    private val api: SchedulerApi,
    private val authRepository: AuthRepository
) : ViewModel() {

    private val _state = MutableStateFlow(NotificationsState())
    val state: StateFlow<NotificationsState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            val tenant = authRepository.currentUser.first()?.id ?: "default"
            val items = try {
                val response = api.service.listNotifications(tenant)
                if (response.isSuccessful) {
                    response.body()?.items?.map { it.toDomain() } ?: emptyList()
                } else {
                    emptyList()
                }
            } catch (e: Exception) {
                // Surface as an empty feed rather than crashing the screen.
                emptyList()
            }
            _state.update {
                it.copy(isLoading = false, notifications = items, unreadCount = items.count { n -> !n.isRead })
            }
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
}
