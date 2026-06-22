package com.schedulersystems.scheduler.models.domain

import java.time.Instant
import java.time.LocalTime

data class Schedule(
    val id: String,
    val name: String,
    val tenantId: String,
    val employees: List<Employee>,
    val currentPriorities: List<String>,
    val settings: ScheduleSettings,
    val nextSchedule: List<ShiftRow>,
    val createdAt: Instant,
    val updatedAt: Instant,
    // "active" | "archived" — mirrors the Go API schedule status. Defaulted so existing
    // constructors keep working; used to split My Schedules (active) from Archived.
    val status: String = "active"
)

data class Employee(
    val id: String,
    val name: String,
    val email: String?,
    val phone: String?,
    val role: Role,
    val priorityMap: Map<String, Int>
)

data class Shift(
    val day: String,
    val startTime: LocalTime,
    val endTime: LocalTime,
    val assignedWorker: String?
)

data class ShiftRow(
    val shifts: List<Shift>
)

data class ScheduleSettings(
    val submissionDeadline: SubmissionDeadline?,
    val enabledShifts: EnabledShifts,
    val timezone: String
)

data class SubmissionDeadline(
    val enabled: Boolean,
    val deadline: Instant?
)

data class EnabledShifts(
    val mornings: Boolean,
    val afternoons: Boolean,
    val evenings: Boolean
)

enum class Role {
    EMPLOYER,
    EMPLOYEE,
    ADMIN
}
