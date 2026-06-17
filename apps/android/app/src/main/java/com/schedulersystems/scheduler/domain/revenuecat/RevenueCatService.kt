package com.schedulersystems.scheduler.domain.revenuecat

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject
import javax.inject.Singleton

data class EntitlementCheckResult(
    val tier: SubscriptionTier,
    val isPremium: Boolean,
    val maxStations: Int,
    val maxEmployees: Int,
    val activeEntitlements: List<String>
)

@Singleton
class RevenueCatService @Inject constructor() {

    private val _currentTier = MutableStateFlow(SubscriptionTier.FREE)
    val currentTier: StateFlow<SubscriptionTier> = _currentTier.asStateFlow()

    private val _isPremium = MutableStateFlow(false)
    val isPremium: StateFlow<Boolean> = _isPremium.asStateFlow()

    fun initialize(apiKey: String) {
        // TODO: RevenueCat v7 SDK initialization
    }

    fun login(userId: String, onError: (Exception) -> Unit = {}) {
        // TODO: RevenueCat v7 login
    }

    fun logout(onComplete: () -> Unit = {}) {
        _currentTier.value = SubscriptionTier.FREE
        _isPremium.value = false
        onComplete()
    }

    suspend fun purchasePackage(packageIdentifier: String, activity: android.app.Activity): Boolean {
        return false
    }

    suspend fun restorePurchases(): Boolean {
        return false
    }

    fun checkEntitlements(): EntitlementCheckResult {
        return EntitlementCheckResult(
            tier = SubscriptionTier.FREE,
            isPremium = false,
            maxStations = SubscriptionTier.FREE.stations,
            maxEmployees = SubscriptionTier.FREE.employees,
            activeEntitlements = emptyList()
        )
    }

    suspend fun isEntitled(entitlementId: String): Boolean? {
        return false
    }

    fun exceedsStationsLimit(count: Int): Boolean {
        return false
    }

    fun exceedsEmployeesLimit(count: Int): Boolean {
        return false
    }

    fun getTierConfigs(): List<TierConfig> = emptyList()
}
