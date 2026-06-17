package com.schedulersystems.scheduler.models.domain

data class User(
    val id: String,
    val email: String?,
    val phone: String?,
    val displayName: String?,
    val role: Role?,
    val isPremium: Boolean,
    val tenantId: String?
)
