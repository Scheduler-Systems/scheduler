package com.schedulersystems.scheduler.models.domain

import java.time.Instant

data class Notification(
    val id: String,
    val isRead: Boolean,
    val fromUser: String?,
    val toUser: String?,
    val content: String,
    val type: NotificationType,
    val chatRefId: String?,
    val timeCreated: Instant
)

enum class NotificationType {
    CHAT_MESSAGE,
    SCHEDULE_REQUEST,
    SCHEDULE_CHANGE,
    SHIFT_CHANGE,
    SYSTEM
}
