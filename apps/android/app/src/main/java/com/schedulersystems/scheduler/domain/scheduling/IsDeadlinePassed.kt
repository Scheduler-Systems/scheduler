package com.schedulersystems.scheduler.domain.scheduling

import java.util.Calendar
import java.util.Date

val WEEKDAY_MAP = mapOf(
    "Sunday" to 0, "Monday" to 1, "Tuesday" to 2, "Wednesday" to 3,
    "Thursday" to 4, "Friday" to 5, "Saturday" to 6
)

fun isDeadlinePassed(
    deadlineWeekday: String,
    deadlineTime: String,
    currentTime: Date
): Boolean {
    val deadlineDay = WEEKDAY_MAP[deadlineWeekday] ?: return false

    val parts = deadlineTime.split(":")
    if (parts.size != 2) return false
    val deadlineHour = parts[0].toIntOrNull() ?: return false
    val deadlineMinute = parts[1].toIntOrNull() ?: return false

    val cal = Calendar.getInstance()
    cal.time = currentTime
    cal.set(Calendar.HOUR_OF_DAY, deadlineHour)
    cal.set(Calendar.MINUTE, deadlineMinute)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)
    val todayDeadline = cal.time

    val currentDay = Calendar.getInstance().apply { time = currentTime }.get(Calendar.DAY_OF_WEEK) - 1
    val daysUntilDeadline = deadlineDay - currentDay

    return daysUntilDeadline < 0 || (daysUntilDeadline == 0 && currentTime.after(todayDeadline))
}
