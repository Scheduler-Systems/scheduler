package com.schedulersystems.scheduler.domain.scheduling

data class BusiestDaysInput(
    val builtSchedules: List<BuiltSchedule>
)

fun findBusiestDays(input: BusiestDaysInput): List<String> {
    val employeeCountPerDay = IntArray(7)

    for (schedule in input.builtSchedules) {
        val priorities = schedule.currentPriorities
        for (i in priorities.indices) {
            if (priorities[i].isNotEmpty()) {
                val employeeCount = priorities[i].split(",").size
                val dayIndex = i / 3
                employeeCountPerDay[dayIndex] += employeeCount
            }
        }
    }

    val maxCount = employeeCountPerDay.maxOrNull() ?: 0
    if (maxCount == 0) return emptyList()

    return DAYS_OF_WEEK.filterIndexed { i, _ -> employeeCountPerDay[i] == maxCount }
}
