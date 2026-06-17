package com.schedulersystems.scheduler.models.domain

import java.time.Instant

data class BuiltSchedule(
    val id: String,
    val schedule: List<List<List<String>>>,
    val firstWeekday: String,
    val lastWeekday: String,
    val currentPriorities: List<String>,
    val firstWeekdayDatetime: Instant?,
    val lastWeekdayDatetime: Instant?,
    val timeCreated: Instant
)
