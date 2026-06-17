package com.schedulersystems.scheduler.domain.scheduling

enum class Period { WEEK, MONTH }

data class AttendanceInput(
    val userId: String,
    val scheduleId: String,
    val isEmployer: Boolean,
    val period: Period,
    val enabledShifts: EnabledShifts,
    val builtSchedules: List<BuiltSchedule>,
    val employeeName: String? = null
)

fun getAttendance(input: AttendanceInput): Double? {
    if (input.builtSchedules.isEmpty()) return null

    if (input.isEmployer) {
        val allPriorities = input.builtSchedules.flatMap { it.currentPriorities }
        val total = allPriorities.size
        val occupied = allPriorities.count { it.isNotEmpty() }
        if (total == 0) return null
        return (occupied.toDouble() / total) * 100.0
    } else {
        val employeeName = input.employeeName ?: ""
        val allPriorities = input.builtSchedules.flatMap { it.currentPriorities }
        val occupied = allPriorities.count { it.contains(employeeName) }
        val total = allPriorities.size
        if (total == 0) return null
        return (occupied.toDouble() / total) * 100.0
    }
}
