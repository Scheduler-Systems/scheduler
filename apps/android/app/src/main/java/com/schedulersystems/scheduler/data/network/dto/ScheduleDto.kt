package com.schedulersystems.scheduler.data.network.dto

import com.google.gson.annotations.SerializedName
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.Shift
import com.schedulersystems.scheduler.models.domain.ShiftRow
import java.time.Instant
import java.time.LocalTime

data class ScheduleListResponse(
    @SerializedName("items") val schedules: List<ScheduleDto>
)

data class ScheduleDto(
    @SerializedName("id") val id: String? = null,
    @SerializedName("name") val name: String,
    @SerializedName("tenantId") val tenantId: String,
    // Nullable because gson ignores Kotlin defaults — an absent JSON field becomes null,
    // not emptyList(), so .map{} on it would NPE. toDomain() coalesces to emptyList().
    @SerializedName("employees") val employees: List<EmployeeDto>? = null,
    @SerializedName("current_priorities") val currentPriorities: List<String>? = null,
    @SerializedName("settings") val settings: ScheduleSettingsDto? = null,
    @SerializedName("next_schedule") val nextSchedule: List<ShiftRowDto>? = null,
    @SerializedName("created_at") val createdAt: String? = null,
    @SerializedName("updated_at") val updatedAt: String? = null
)

data class EmployeeDto(
    @SerializedName("id") val id: String,
    @SerializedName("name") val name: String,
    @SerializedName("email") val email: String? = null,
    @SerializedName("phone") val phone: String? = null,
    @SerializedName("role") val role: String = "EMPLOYEE",
    @SerializedName("priority_map") val priorityMap: Map<String, Int> = emptyMap()
)

data class ScheduleSettingsDto(
    @SerializedName("enabled_shifts") val enabledShifts: EnabledShiftsDto = EnabledShiftsDto(),
    @SerializedName("timezone") val timezone: String = "UTC"
)

data class EnabledShiftsDto(
    @SerializedName("morning") val mornings: Boolean = false,
    @SerializedName("afternoon") val afternoons: Boolean = false,
    @SerializedName("night") val evenings: Boolean = false
)

data class ShiftRowDto(
    @SerializedName("shifts") val shifts: List<ShiftDto> = emptyList()
)

data class ShiftDto(
    @SerializedName("day") val day: String,
    @SerializedName("start_time") val startTime: String,
    @SerializedName("end_time") val endTime: String,
    @SerializedName("assigned_worker") val assignedWorker: String? = null
)

fun ScheduleDto.toDomain(): Schedule {
    return Schedule(
        id = id ?: "",
        name = name,
        tenantId = tenantId,
        employees = employees?.map { it.toDomain() } ?: emptyList(),
        currentPriorities = currentPriorities ?: emptyList(),
        settings = (settings ?: ScheduleSettingsDto()).toDomain(),
        nextSchedule = nextSchedule?.map { it.toDomain() } ?: emptyList(),
        createdAt = parseInstantOrNow(createdAt),
        updatedAt = parseInstantOrNow(updatedAt)
    )
}

fun Schedule.toDto(): ScheduleDto {
    return ScheduleDto(
        id = id.ifEmpty { null },
        name = name,
        tenantId = tenantId,
        employees = employees.map { it.toDto() },
        currentPriorities = currentPriorities,
        settings = settings.toDto(),
        nextSchedule = nextSchedule.map { it.toDto() },
        createdAt = createdAt.toString(),
        updatedAt = updatedAt.toString()
    )
}

private fun EmployeeDto.toDomain(): Employee {
    return Employee(
        id = id,
        name = name,
        email = email,
        phone = phone,
        role = try {
            Role.valueOf(role.uppercase())
        } catch (_: Exception) {
            Role.EMPLOYEE
        },
        priorityMap = priorityMap
    )
}

private fun Employee.toDto(): EmployeeDto {
    return EmployeeDto(
        id = id,
        name = name,
        email = email,
        phone = phone,
        role = role.name,
        priorityMap = priorityMap
    )
}

private fun ScheduleSettingsDto.toDomain(): ScheduleSettings {
    return ScheduleSettings(
        submissionDeadline = null,
        enabledShifts = EnabledShifts(
            mornings = enabledShifts.mornings,
            afternoons = enabledShifts.afternoons,
            evenings = enabledShifts.evenings
        ),
        timezone = timezone
    )
}

private fun ScheduleSettings.toDto(): ScheduleSettingsDto {
    return ScheduleSettingsDto(
        enabledShifts = EnabledShiftsDto(
            mornings = enabledShifts.mornings,
            afternoons = enabledShifts.afternoons,
            evenings = enabledShifts.evenings
        ),
        timezone = timezone
    )
}

private fun ShiftRowDto.toDomain(): ShiftRow {
    return ShiftRow(
        shifts = shifts.map { it.toDomain() }
    )
}

private fun ShiftRow.toDto(): ShiftRowDto {
    return ShiftRowDto(
        shifts = shifts.map { it.toDto() }
    )
}

private fun ShiftDto.toDomain(): Shift {
    return Shift(
        day = day,
        startTime = try { LocalTime.parse(startTime) } catch (_: Exception) { LocalTime.MIDNIGHT },
        endTime = try { LocalTime.parse(endTime) } catch (_: Exception) { LocalTime.MIDNIGHT },
        assignedWorker = assignedWorker
    )
}

private fun Shift.toDto(): ShiftDto {
    return ShiftDto(
        day = day,
        startTime = startTime.toString(),
        endTime = endTime.toString(),
        assignedWorker = assignedWorker
    )
}

private fun parseInstantOrNow(value: String?): Instant {
    return try {
        if (value != null) Instant.parse(value) else Instant.now()
    } catch (_: Exception) {
        Instant.now()
    }
}
