package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName
import com.schedulersystems.scheduler.models.domain.RequestStatus
import com.schedulersystems.scheduler.models.domain.ScheduleRequest
import java.time.Instant

// Schedule invitation as served by the Go API
// (GET .../schedules/{id}/employees/invitations → {items:[...]}). camelCase keys mirror
// the Go Invitation struct. Status uses the preserved Flutter enum strings (incl. the
// "ADD_RQUEST_PENDING" typo).
data class InvitationListResponse(
    @SerializedName("items") val items: List<InvitationDto>? = null
)

data class InvitationDto(
    @SerializedName("id") val id: String,
    @SerializedName("scheduleId") val scheduleId: String? = null,
    @SerializedName("scheduleName") val scheduleName: String? = null,
    @SerializedName("fromUserId") val fromUserId: String? = null,
    @SerializedName("toUserId") val toUserId: String? = null,
    @SerializedName("toUserIdentification") val toUserIdentification: String? = null,
    @SerializedName("isAddRequest") val isAddRequest: Boolean? = null,
    @SerializedName("isJoinRequest") val isJoinRequest: Boolean? = null,
    @SerializedName("status") val status: String? = null,
    @SerializedName("createdAt") val createdAt: String? = null
)

fun InvitationDto.toDomain(): ScheduleRequest {
    val s = status ?: ""
    val mappedStatus = when {
        s.endsWith("ACCEPTED") -> RequestStatus.APPROVED
        s.endsWith("DECLINED") -> RequestStatus.DECLINED
        s.startsWith("JOIN") -> RequestStatus.JOIN_REQUEST_PENDING
        else -> RequestStatus.ADD_REQUEST_PENDING
    }
    return ScheduleRequest(
        id = id,
        scheduleName = scheduleName ?: "",
        scheduleRef = scheduleId ?: "",
        fromUser = fromUserId,
        toUser = toUserId,
        toUserIdentification = toUserIdentification ?: "",
        isAddRequest = isAddRequest ?: true,
        isJoinRequest = isJoinRequest ?: false,
        requestStatus = mappedStatus,
        isRead = false,
        createdTime = try { if (createdAt != null) Instant.parse(createdAt) else Instant.now() } catch (_: Exception) { Instant.now() }
    )
}
