package com.schedulersystems.scheduler.domain.scheduling

import java.util.Calendar

data class CalculateUserAttendanceInput(
    val scheduleId: String,
    val userId: String,
    val period: Period,
    val enabledShifts: EnabledShifts,
    val builtSchedules: List<BuiltSchedule>,
    val role: UserRole,
    val employeeName: String
)

enum class UserRole { EMPLOYER, EMPLOYEE }

fun calculateUserAttendance(input: CalculateUserAttendanceInput): String {
    val shiftCount = enabledShiftCount(input.enabledShifts)

    val now = Calendar.getInstance()
    val totalShifts = when (input.period) {
        Period.WEEK -> shiftCount * 7
        Period.MONTH -> {
            val daysInMonth = now.getActualMaximum(Calendar.DAY_OF_MONTH)
            shiftCount * daysInMonth
        }
    }

    var occupiedShifts = 0
    for (doc in input.builtSchedules) {
        val priorities = doc.currentPriorities
        if (input.role == UserRole.EMPLOYER) {
            occupiedShifts += priorities.count { it.isNotEmpty() }
        } else {
            occupiedShifts += priorities.count { it.contains(input.employeeName) }
        }
    }

    return "$occupiedShifts/$totalShifts"
}
