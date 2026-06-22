package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName

// User-profile (users/{uid}) auth onboarding. The server computes the role STRING from
// this RoleStruct (parity with scheduler-web's roleStructToFlutterString); role is never
// taken from a header.
data class RoleStructDto(
    @SerializedName("is_creator") val isCreator: Boolean,
    @SerializedName("is_admin") val isAdmin: Boolean,
    @SerializedName("is_worker") val isWorker: Boolean
)

data class UpsertProfileRequestDto(
    @SerializedName("email") val email: String,
    @SerializedName("display_name") val displayName: String
)

data class UpsertRoleRequestDto(
    @SerializedName("email") val email: String,
    @SerializedName("role") val role: RoleStructDto
)

// Manager → creator+admin; employee → worker. Pure mapping (unit-tested), matches iOS +
// the Go handler's expectations.
fun roleStructFor(isManager: Boolean): RoleStructDto =
    RoleStructDto(isCreator = isManager, isAdmin = isManager, isWorker = !isManager)
