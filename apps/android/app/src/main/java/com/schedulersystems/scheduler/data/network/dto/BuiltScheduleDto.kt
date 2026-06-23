package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName

/**
 * Request body for POST /schedules/{id}/built-schedules. The grid is the 3-D
 * `[station][day][shift]` assignment matrix produced by ShiftAssigner.assignShifts
 * (null cells normalized to "" before sending — the Go API + render want non-null).
 */
data class BuiltScheduleSaveRequest(
    @SerializedName("schedule") val schedule: List<List<List<String>>>,
    @SerializedName("first_weekday") val firstWeekday: String = "",
    @SerializedName("last_weekday") val lastWeekday: String = "",
    @SerializedName("current_priorities") val currentPriorities: List<String> = emptyList()
)

/**
 * The built-schedule document returned by the Go API. Nullable fields because gson
 * ignores Kotlin defaults (an absent JSON field decodes to null, not the default).
 */
data class BuiltScheduleDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("schedule") val schedule: List<List<List<String>>>? = null,
    @SerializedName("first_weekday") val firstWeekday: String? = null,
    @SerializedName("last_weekday") val lastWeekday: String? = null,
    @SerializedName("current_priorities") val currentPriorities: List<String>? = null,
    @SerializedName("time_created") val timeCreated: String? = null,
    @SerializedName("createdBy") val createdBy: String? = null
)
