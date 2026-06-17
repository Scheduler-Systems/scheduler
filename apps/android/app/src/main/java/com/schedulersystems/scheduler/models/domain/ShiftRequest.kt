package com.schedulersystems.scheduler.models.domain

import java.time.Instant

data class ShiftRequest(
    val id: String,
    val requestingEmployee: String,
    val shiftToChangeFrom: Instant,
    val shiftToChangeTo: Instant,
    val builtScheduleRef: String?,
    val status: ShiftRequestStatus,
    val createdTime: Instant
)

enum class ShiftRequestStatus {
    PENDING,
    APPROVED,
    DECLINED
}
