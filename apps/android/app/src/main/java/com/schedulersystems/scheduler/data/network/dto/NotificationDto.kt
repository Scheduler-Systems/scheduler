package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName
import com.schedulersystems.scheduler.models.domain.Notification
import com.schedulersystems.scheduler.models.domain.NotificationType
import java.time.Instant

// Notification feed from the Go API (GET .../notifications → {items:[...]}). camelCase
// keys mirror the Go Notification struct.
data class NotificationListResponse(
    @SerializedName("items") val items: List<NotificationDto>? = null
)

data class NotificationDto(
    @SerializedName("id") val id: String,
    @SerializedName("userId") val userId: String? = null,
    @SerializedName("fromUser") val fromUser: String? = null,
    @SerializedName("content") val content: String? = null,
    @SerializedName("type") val type: String? = null,
    @SerializedName("chatRefId") val chatRefId: String? = null,
    @SerializedName("isRead") val isRead: Boolean? = null,
    @SerializedName("createdAt") val createdAt: String? = null
)

fun NotificationDto.toDomain(): Notification = Notification(
    id = id,
    isRead = isRead ?: false,
    fromUser = fromUser,
    toUser = userId,
    content = content ?: "",
    type = mapNotificationType(type),
    chatRefId = chatRefId,
    timeCreated = try {
        if (createdAt != null) Instant.parse(createdAt) else Instant.now()
    } catch (_: Exception) { Instant.now() }
)

private fun mapNotificationType(raw: String?): NotificationType = try {
    NotificationType.valueOf((raw ?: "SYSTEM").uppercase())
} catch (_: Exception) {
    NotificationType.SYSTEM
}
