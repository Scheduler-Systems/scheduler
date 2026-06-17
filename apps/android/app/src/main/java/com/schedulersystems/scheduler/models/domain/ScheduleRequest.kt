package com.schedulersystems.scheduler.models.domain

data class ScheduleRequest(
    val id: String,
    val scheduleName: String,
    val scheduleRef: String,
    val fromUser: String?,
    val toUser: String?,
    val toUserIdentification: String,
    val isAddRequest: Boolean,
    val isJoinRequest: Boolean,
    val requestStatus: RequestStatus,
    val isRead: Boolean,
    val createdTime: java.time.Instant
)

enum class RequestStatus {
    ADD_REQUEST_PENDING,
    JOIN_REQUEST_PENDING,
    APPROVED,
    DECLINED,
    EXPIRED
}
