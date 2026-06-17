package com.schedulersystems.scheduler.models.ui

import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule

data class HomeUiState(
    val isLoading: Boolean = false,
    val schedules: List<Schedule> = emptyList(),
    val error: String? = null,
    val userRole: Role? = null,
    val displayName: String? = null
)

data class ScheduleBuildUiState(
    val schedule: Schedule? = null,
    val shiftRows: List<com.schedulersystems.scheduler.models.domain.ShiftRow> = emptyList(),
    val isSaving: Boolean = false,
    val selectedCell: Pair<Int, Int>? = null,
    val error: String? = null
)

data class EmployeeListUiState(
    val isLoading: Boolean = false,
    val employees: List<com.schedulersystems.scheduler.models.domain.Employee> = emptyList(),
    val scheduleName: String = "",
    val error: String? = null
)

data class PrioritiesUiState(
    val isLoading: Boolean = false,
    val priorities: List<String> = emptyList(),
    val submittedPriorities: List<String> = emptyList(),
    val isSubmitting: Boolean = false,
    val error: String? = null
)

data class ChatUiState(
    val isLoading: Boolean = false,
    val chats: List<ChatItem> = emptyList(),
    val error: String? = null
)

data class ChatItem(
    val id: String,
    val name: String,
    val lastMessage: String?,
    val timestamp: Long,
    val unreadCount: Int
)
