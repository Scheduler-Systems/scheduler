package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Role

// Wire shapes for the Go API's schedule-roster endpoint
// (GET/POST /v1/tenants/{tid}/schedules/{sid}/employees). These mirror
// scheduler-web's EmployeeDetails (snake_case, role object), which is distinct
// from the legacy embedded EmployeeDto in ScheduleDto.kt — the roster is served
// from its own endpoint, not embedded in the schedule document. Identity is the
// email (matches the server's add/remove/dedup rule and the iOS client).

data class EmployeeListApiResponse(
    // Nullable: gson ignores Kotlin defaults, so an absent "items" becomes null,
    // not emptyList() — coalesced by the caller.
    @SerializedName("items") val items: List<ApiEmployeeDto>? = null
)

data class ApiEmployeeDto(
    @SerializedName("employee_name") val employeeName: String? = null,
    @SerializedName("employee_email") val employeeEmail: String? = null,
    @SerializedName("employee_phone") val employeePhone: String? = null,
    @SerializedName("role") val role: ApiEmployeeRoleDto? = null,
    @SerializedName("user_ref") val userRef: String? = null
)

data class ApiEmployeeRoleDto(
    @SerializedName("is_creator") val isCreator: Boolean? = null,
    @SerializedName("is_admin") val isAdmin: Boolean? = null,
    @SerializedName("is_worker") val isWorker: Boolean? = null
)

fun ApiEmployeeDto.toDomain(): Employee {
    val resolvedRole = when {
        role?.isAdmin == true -> Role.ADMIN
        role?.isCreator == true -> Role.EMPLOYER
        else -> Role.EMPLOYEE
    }
    val email = employeeEmail ?: ""
    return Employee(
        // email is the API's stable identity → used as the domain id (matches iOS).
        id = email,
        name = employeeName ?: email,
        email = employeeEmail,
        phone = employeePhone,
        role = resolvedRole,
        priorityMap = emptyMap()
    )
}

// Add-employee request body (snake_case, role object), mirroring the server's
// employeeInput. is_worker default true matches the server default for staff.
data class AddEmployeeApiRequest(
    @SerializedName("employee_name") val employeeName: String,
    @SerializedName("employee_email") val employeeEmail: String,
    @SerializedName("employee_phone") val employeePhone: String,
    @SerializedName("role") val role: ApiEmployeeRoleDto = ApiEmployeeRoleDto(isWorker = true)
)

fun Employee.toAddRequest(): AddEmployeeApiRequest {
    return AddEmployeeApiRequest(
        employeeName = name,
        employeeEmail = email ?: "",
        employeePhone = phone ?: "",
        role = when (role) {
            Role.ADMIN -> ApiEmployeeRoleDto(isAdmin = true)
            Role.EMPLOYER -> ApiEmployeeRoleDto(isCreator = true)
            Role.EMPLOYEE -> ApiEmployeeRoleDto(isWorker = true)
        }
    )
}
