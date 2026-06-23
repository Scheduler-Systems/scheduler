package com.schedulersystems.scheduler.domain.export

/**
 * Pure, framework-free model of the printable schedule PDF. The row-expansion,
 * title, and filename rules are a faithful port of the web's lib/pdf-export.ts
 * (the production-canonical reference) — kept off any android.graphics class so
 * it stays JVM-unit-testable. SchedulePdfRenderer turns this into real PDF bytes.
 *
 * Native built schedules carry only the assignment grid (employee names per
 * day/shift) — the Go API persists no per-shift hours or per-cell priorities — so
 * the table is Shift · Day · Employee, the real data we actually have. (The web
 * adds Start/End/Priority columns sourced from settings the native model does not
 * store; fabricating blank columns here would be speculative, so they are omitted.)
 */

private val DAY_LABELS = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

data class SchedulePdfRow(
    val shift: String,
    val day: String,
    val employee: String
)

data class SchedulePdfDoc(
    val title: String,
    val filename: String,
    val rows: List<SchedulePdfRow>
) {
    companion object {
        /** Contractually-fixed header order (see SchedulePdfTest). */
        val HEADER = listOf("Shift", "Day", "Employee")
    }
}

/** Deterministic ordinal -> label for days (e.g. "Sun #1"). */
private fun formatDay(dayIndex: Int): String = "${DAY_LABELS[dayIndex % 7]} #${dayIndex + 1}"

/** "{name} Schedule · {first} — {last}"; range omitted when both weekdays blank. */
fun schedulePdfTitle(scheduleName: String, firstWeekday: String = "", lastWeekday: String = ""): String {
    val name = scheduleName.trim().ifEmpty { "Untitled" }
    val first = firstWeekday.trim()
    val last = lastWeekday.trim()
    val range = when {
        first.isNotEmpty() && last.isNotEmpty() -> "$first — $last"
        else -> first.ifEmpty { last }
    }
    return if (range.isNotEmpty()) "$name Schedule · $range" else "$name Schedule"
}

/** Sanitizes unsafe filesystem characters; falls back to "schedule". */
fun schedulePdfFilename(scheduleName: String): String {
    val base = scheduleName.trim().ifEmpty { "schedule" }
    val safe = base.replace(Regex("[^a-zA-Z0-9-_]+"), "_").trim('_')
    return "${safe.ifEmpty { "schedule" }}.pdf"
}

/**
 * Expands the day-major grid (grid[day][shift] = the station name(s) for that
 * slot) into one table row per assigned worker; an unassigned slot yields a
 * single placeholder row with a blank employee — mirrors the web's roster shape.
 */
fun buildSchedulePdfRows(
    enabledShifts: List<String>,
    grid: List<List<List<String>>>
): List<SchedulePdfRow> {
    val shifts = enabledShifts.ifEmpty { listOf("") }
    val out = mutableListOf<SchedulePdfRow>()
    grid.forEachIndexed { d, dayShifts ->
        for (s in shifts.indices) {
            val names = dayShifts.getOrNull(s).orEmpty().filter { it.isNotBlank() }
            val shift = shifts[s]
            val day = formatDay(d)
            if (names.isEmpty()) {
                out.add(SchedulePdfRow(shift, day, ""))
            } else {
                names.forEach { out.add(SchedulePdfRow(shift, day, it)) }
            }
        }
    }
    return out
}

fun buildSchedulePdfDoc(
    scheduleName: String,
    enabledShifts: List<String>,
    grid: List<List<List<String>>>,
    firstWeekday: String = "",
    lastWeekday: String = ""
): SchedulePdfDoc = SchedulePdfDoc(
    title = schedulePdfTitle(scheduleName, firstWeekday, lastWeekday),
    filename = schedulePdfFilename(scheduleName),
    rows = buildSchedulePdfRows(enabledShifts, grid)
)
