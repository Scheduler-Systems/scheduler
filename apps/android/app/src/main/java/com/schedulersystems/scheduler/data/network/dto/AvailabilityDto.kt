package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName

// Request body for POST .../schedules/{id}/availability. The Go API stores the
// arbitrary `availability` map under a pending approval entry (202 Accepted). The
// priorities-submission screen submits the user's selected priority slots here.
data class AvailabilityRequestDto(
    @SerializedName("availability") val availability: Map<String, Any>
)
