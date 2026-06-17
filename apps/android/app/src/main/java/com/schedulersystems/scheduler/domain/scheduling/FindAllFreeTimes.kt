package com.schedulersystems.scheduler.domain.scheduling

data class FreeTimeInput(
    val enabledShifts: EnabledShifts,
    val builtSchedules: List<BuiltSchedule>
)

fun findAllFreeTimes(input: FreeTimeInput): List<String> {
    val assignedSlots = mutableSetOf<Int>()

    for (doc in input.builtSchedules) {
        val builtList = doc.schedule.firstOrNull()?.get("stringList") ?: emptyList()
        for (i in builtList.indices) {
            if (builtList[i].isNotEmpty()) {
                assignedSlots.add(i)
            }
        }
    }

    val freeTimeSlots = mutableListOf<String>()
    for (dayIndex in 0 until 7) {
        val day = DAYS_OF_WEEK[dayIndex]

        if (input.enabledShifts.morning) {
            val idx = dayIndex * 3 + shiftIndex(ShiftType.MORNING)
            if (idx !in assignedSlots) {
                freeTimeSlots.add("$day, ${input.enabledShifts.morningShiftTime}")
            }
        }
        if (input.enabledShifts.afternoon) {
            val idx = dayIndex * 3 + shiftIndex(ShiftType.AFTERNOON)
            if (idx !in assignedSlots) {
                freeTimeSlots.add("$day, ${input.enabledShifts.afternoonShiftTime}")
            }
        }
        if (input.enabledShifts.night) {
            val idx = dayIndex * 3 + shiftIndex(ShiftType.NIGHT)
            if (idx !in assignedSlots) {
                freeTimeSlots.add("$day, ${input.enabledShifts.nightShiftTime}")
            }
        }
    }

    return freeTimeSlots.distinct()
}
