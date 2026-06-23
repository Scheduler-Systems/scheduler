package com.schedulersystems.scheduler.domain.export

import java.time.LocalDate

/**
 * Pure, framework-free generator of an iCalendar (.ics, RFC 5545) export of the built
 * schedule. One all-day VEVENT per assigned (day, shift, employee) — anchored to a week
 * starting at [weekStartEpochDay]. All-day (VALUE=DATE) events avoid fabricating shift
 * hours the native built-schedule doesn't carry (same honest stance as SchedulePdf's
 * Shift·Day·Employee columns). The result imports into Google Calendar and every other
 * calendar app — a credential-free, real export (no Google OAuth dependency).
 */
private val DAY_LABELS = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

/** Sanitizes a value for an iCalendar TEXT field (RFC 5545 §3.3.11). */
private fun icsEscape(s: String): String =
    s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

fun scheduleIcsFilename(scheduleName: String): String {
    val base = scheduleName.trim().ifEmpty { "schedule" }
    val safe = base.replace(Regex("[^a-zA-Z0-9-_]+"), "_").trim('_')
    return "${safe.ifEmpty { "schedule" }}.ics"
}

/**
 * Builds the .ics text. [grid] is day-major: grid[day][shift] = the assigned name(s).
 * [enabledShifts] labels the shift index. Returns a complete VCALENDAR; always valid even
 * when the grid is empty (a calendar with zero events).
 */
fun buildScheduleIcs(
    scheduleName: String,
    enabledShifts: List<String>,
    grid: List<List<List<String>>>,
    weekStartEpochDay: Long
): String {
    val shifts = enabledShifts.ifEmpty { listOf("Shift") }
    val sb = StringBuilder()
    sb.append("BEGIN:VCALENDAR\r\n")
    sb.append("VERSION:2.0\r\n")
    sb.append("PRODID:-//Scheduler Systems//Schedule Export//EN\r\n")
    sb.append("CALSCALE:GREGORIAN\r\n")
    sb.append("X-WR-CALNAME:${icsEscape(scheduleName.ifBlank { "Schedule" })}\r\n")
    var seq = 0
    grid.forEachIndexed { dayIndex, dayShifts ->
        val date = LocalDate.ofEpochDay(weekStartEpochDay + dayIndex)
        val dateStr = "%04d%02d%02d".format(date.year, date.monthValue, date.dayOfMonth)
        val nextStr = date.plusDays(1).let { "%04d%02d%02d".format(it.year, it.monthValue, it.dayOfMonth) }
        for (s in shifts.indices) {
            val names = dayShifts.getOrNull(s).orEmpty().filter { it.isNotBlank() }
            for (name in names) {
                seq++
                sb.append("BEGIN:VEVENT\r\n")
                sb.append("UID:sched-${dateStr}-${s}-${seq}@scheduler-systems\r\n")
                sb.append("DTSTART;VALUE=DATE:$dateStr\r\n")
                sb.append("DTEND;VALUE=DATE:$nextStr\r\n")
                sb.append("SUMMARY:${icsEscape("${shifts[s]} shift — $name")}\r\n")
                sb.append("DESCRIPTION:${icsEscape("$name · ${shifts[s]} · ${DAY_LABELS[dayIndex % 7]}")}\r\n")
                sb.append("END:VEVENT\r\n")
            }
        }
    }
    sb.append("END:VCALENDAR\r\n")
    return sb.toString()
}
