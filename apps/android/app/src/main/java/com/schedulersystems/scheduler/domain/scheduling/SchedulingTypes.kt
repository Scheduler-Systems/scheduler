package com.schedulersystems.scheduler.domain.scheduling

import java.util.Date

val DAYS_OF_WEEK = listOf(
    "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"
)

enum class ShiftType { MORNING, AFTERNOON, NIGHT }

fun shiftIndex(type: ShiftType): Int = when (type) {
    ShiftType.MORNING -> 0
    ShiftType.AFTERNOON -> 1
    ShiftType.NIGHT -> 2
}

typealias SlotArray = List<String>

data class EnabledShifts(
    val morning: Boolean = true,
    val afternoon: Boolean = true,
    val night: Boolean = true,
    val morningShiftTime: String = "07:00 - 15:00",
    val afternoonShiftTime: String = "15:00 - 23:00",
    val nightShiftTime: String = "23:00 - 07:00"
)

data class BuiltSchedule(
    val schedule: List<Map<String, List<String>>>,
    val firstWeekdayDatetime: Date,
    val lastWeekdayDatetime: Date,
    val currentPriorities: List<String>
)

data class StationConfig(
    val morning: Boolean = true,
    val afternoon: Boolean = true,
    val night: Boolean = true,
    val numOfPeople: Int,
    val stationNum: Int
)

fun slotIndex(dayIndex: Int, shiftType: ShiftType): Int {
    return dayIndex * 3 + shiftIndex(shiftType)
}

fun dayIndexFromSlot(slotIdx: Int): Int = slotIdx / 3
fun shiftIndexFromSlot(slotIdx: Int): Int = slotIdx % 3

fun gridToArray(grid: List<List<String?>>): List<String> {
    val result = mutableListOf<String>()
    for (day in 0 until 7) {
        for (shift in 0 until 3) {
            result.add(grid[day][shift] ?: "")
        }
    }
    return result
}

fun enabledShiftCount(shifts: EnabledShifts): Int {
    return (if (shifts.morning) 1 else 0) +
            (if (shifts.afternoon) 1 else 0) +
            (if (shifts.night) 1 else 0)
}

data class StationEntitlementDecision(
    val allowed: Boolean,
    val enforcedStationCount: Int,
    val dialogTitle: String? = null,
    val dialogMessage: String? = null,
    val usedLocalBypass: Boolean = false
)

fun evaluateStationEntitlementSelection(
    selectedStationCount: Int,
    isPremiumUser: Boolean,
    activeEntitlements: List<String>?,
    allowLocalDebugBypass: Boolean = false
): StationEntitlementDecision {
    if (selectedStationCount <= 1) {
        return StationEntitlementDecision(allowed = true, enforcedStationCount = 1)
    }
    if (allowLocalDebugBypass) {
        return StationEntitlementDecision(
            allowed = true,
            enforcedStationCount = selectedStationCount,
            usedLocalBypass = true
        )
    }
    if (!isPremiumUser) {
        return StationEntitlementDecision(
            allowed = false,
            enforcedStationCount = 1,
            dialogTitle = "Premium Required",
            dialogMessage = "Multiple stations require a premium subscription."
        )
    }

    val normalized = (activeEntitlements ?: emptyList())
        .map { it.lowercase() }
        .filter { !it.contains("employee") }

    if (normalized.isEmpty()) {
        return StationEntitlementDecision(
            allowed = false, enforcedStationCount = 1,
            dialogTitle = "Subscription Check Failed",
            dialogMessage = "We could not verify your premium entitlements."
        )
    }

    val hasEssentialsOrPro = normalized.any { it.contains("essentials") || it.contains("pro") }
    val hasPro = normalized.any { it.contains("pro") }

    if (selectedStationCount <= 3 && hasEssentialsOrPro) {
        return StationEntitlementDecision(allowed = true, enforcedStationCount = selectedStationCount)
    }
    if (selectedStationCount <= 5 && hasPro) {
        return StationEntitlementDecision(allowed = true, enforcedStationCount = selectedStationCount)
    }
    if (selectedStationCount <= 3) {
        return StationEntitlementDecision(
            allowed = false, enforcedStationCount = 1,
            dialogTitle = "Upgrade Required",
            dialogMessage = "Up to 3 stations requires an Essentials or Pro plan."
        )
    }
    return StationEntitlementDecision(
        allowed = false, enforcedStationCount = 1,
        dialogTitle = "Upgrade Required",
        dialogMessage = "4 to 5 stations requires a Pro plan."
    )
}
