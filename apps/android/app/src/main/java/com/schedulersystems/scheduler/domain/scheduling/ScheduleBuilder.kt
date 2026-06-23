package com.schedulersystems.scheduler.domain.scheduling

import java.time.DayOfWeek
import java.time.LocalDate

/**
 * Priority-aware schedule builder — a faithful Kotlin port of the production web
 * algorithm (scheduler-web/lib/schedule-builder.ts buildSchedule). It is the canonical
 * builder; parity with the web is pinned by ScheduleBuilderTest (the web's own test
 * cases as golden outputs).
 *
 * Pick order for each slot:
 *   1. Workers who marked this exact (weekday|shift) cell as priority AND (if
 *      avoidSameDayConflicts) aren't already on that day. Fewest assignments wins.
 *   2. Otherwise fairness round-robin: least-assigned eligible worker, tie-break on
 *      cursor-relative order.
 *
 * Output `rows` is day-major: rows[dayIdx * numShifts + shiftIdx] = the assigned names
 * for that slot (one per station).
 */

data class BuildScheduleInput(
    val employees: List<String>,
    val enabledShifts: List<String>,
    val numDays: Int,
    val numStations: Int,
    val startWeekday: Int = 0, // 0 = Sunday (matches Date.getUTCDay())
    val avoidSameDayConflicts: Boolean = false,
    val priorities: Map<String, Set<String>> = emptyMap()
)

data class ScheduleConflict(val dayIndex: Int, val worker: String, val shifts: List<String>)

data class BuildScheduleOutput(
    val rows: List<List<String>>,
    val conflicts: List<ScheduleConflict>
)

private val WEEKDAYS = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

private fun normName(s: String): String = s.trim().lowercase()

/** Sunday=0..Saturday=6, matching JS Date.getUTCDay() (LocalDate uses Monday=1..Sunday=7). */
fun utcWeekday(date: LocalDate): Int = date.dayOfWeek.value % 7

fun buildSchedule(input: BuildScheduleInput): BuildScheduleOutput {
    val employees = input.employees
    val enabledShifts = input.enabledShifts
    if (input.numDays <= 0 || enabledShifts.isEmpty()) {
        return BuildScheduleOutput(rows = emptyList(), conflicts = emptyList())
    }

    val normalizedPriorities = input.priorities.entries.associate { (k, v) -> normName(k) to v }
    val n = employees.size
    val assignments = HashMap<Int, Int>()
    val rows = mutableListOf<List<String>>()
    var cursor = 0

    fun relativeOrder(a: Int, b: Int): Int =
        ((a - cursor + n) % n) - ((b - cursor + n) % n)

    fun pickIndex(cellKey: String, dayAssigned: Set<String>): Int? {
        if (n == 0) return null

        // 1. Priority candidates: marked this cell AND eligible.
        val priorityIdxs = mutableListOf<Int>()
        for (i in employees.indices) {
            val cell = normalizedPriorities[normName(employees[i])] ?: continue
            if (cellKey !in cell) continue
            if (input.avoidSameDayConflicts && employees[i] in dayAssigned) continue
            priorityIdxs.add(i)
        }
        if (priorityIdxs.isNotEmpty()) {
            return priorityIdxs.sortedWith(Comparator { a, b ->
                val ca = assignments[a] ?: 0
                val cb = assignments[b] ?: 0
                if (ca != cb) ca - cb else relativeOrder(a, b)
            }).first()
        }

        // 2. Fairness fallback: least-assigned eligible worker, cursor-relative tie-break.
        val candidateIdxs = mutableListOf<Int>()
        for (offset in 0 until n) {
            val i = (cursor + offset) % n
            if (input.avoidSameDayConflicts && employees[i] in dayAssigned) continue
            candidateIdxs.add(i)
        }
        if (candidateIdxs.isEmpty()) return null
        return candidateIdxs.sortedWith(Comparator { a, b ->
            val ca = assignments[a] ?: 0
            val cb = assignments[b] ?: 0
            if (ca != cb) ca - cb else relativeOrder(a, b)
        }).first()
    }

    for (d in 0 until input.numDays) {
        val weekday = WEEKDAYS[(input.startWeekday + d) % 7]
        val dayAssigned = HashSet<String>()
        for (s in enabledShifts.indices) {
            val cellKey = "$weekday|${enabledShifts[s]}"
            val stringList = mutableListOf<String>()
            for (k in 0 until input.numStations) {
                val idx = pickIndex(cellKey, dayAssigned)
                if (idx == null) {
                    stringList.add("")
                    continue
                }
                val pick = employees[idx]
                stringList.add(pick)
                dayAssigned.add(pick)
                assignments[idx] = (assignments[idx] ?: 0) + 1
                cursor = (idx + 1) % n
            }
            rows.add(stringList)
        }
    }

    // Conflict detection: a worker on >1 shift the same day.
    val conflicts = mutableListOf<ScheduleConflict>()
    val numShifts = enabledShifts.size
    for (d in 0 until input.numDays) {
        val seen = LinkedHashMap<String, MutableList<String>>()
        for (s in 0 until numShifts) {
            val row = rows[d * numShifts + s]
            for (name in row) {
                if (name.isEmpty()) continue
                val shifts = seen[name]
                if (shifts != null) {
                    if (enabledShifts[s] !in shifts) shifts.add(enabledShifts[s])
                } else {
                    seen[name] = mutableListOf(enabledShifts[s])
                }
            }
        }
        for ((worker, shifts) in seen) {
            if (shifts.size > 1) conflicts.add(ScheduleConflict(d, worker, shifts))
        }
    }

    return BuildScheduleOutput(rows = rows, conflicts = conflicts)
}
