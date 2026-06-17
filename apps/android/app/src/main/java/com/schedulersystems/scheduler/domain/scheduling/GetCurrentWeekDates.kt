package com.schedulersystems.scheduler.domain.scheduling

import java.util.Calendar
import java.util.Date

fun getCurrentWeekDates(deadlineIsOver: Boolean): List<Date> {
    val now = Calendar.getInstance()
    val currentWeekday = now.get(Calendar.DAY_OF_WEEK) - 1

    val startOfWeek = Calendar.getInstance()
    startOfWeek.time = now.time
    if (deadlineIsOver) {
        startOfWeek.add(Calendar.DAY_OF_MONTH, 7 - currentWeekday)
    } else {
        startOfWeek.add(Calendar.DAY_OF_MONTH, -currentWeekday)
    }
    startOfWeek.set(Calendar.HOUR_OF_DAY, 0)
    startOfWeek.set(Calendar.MINUTE, 0)
    startOfWeek.set(Calendar.SECOND, 0)
    startOfWeek.set(Calendar.MILLISECOND, 0)

    return (0 until 7).map { i ->
        Calendar.getInstance().apply {
            time = startOfWeek.time
            add(Calendar.DAY_OF_MONTH, i)
        }.time
    }
}

fun getWeekDates(selectedDate: Date): List<Date> {
    val cal = Calendar.getInstance()
    cal.time = selectedDate
    val currentWeekday = cal.get(Calendar.DAY_OF_WEEK) - 1

    cal.add(Calendar.DAY_OF_MONTH, -currentWeekday)
    cal.set(Calendar.HOUR_OF_DAY, 0)
    cal.set(Calendar.MINUTE, 0)
    cal.set(Calendar.SECOND, 0)
    cal.set(Calendar.MILLISECOND, 0)

    return (0 until 7).map { i ->
        Calendar.getInstance().apply {
            time = cal.time
            add(Calendar.DAY_OF_MONTH, i)
        }.time
    }
}
