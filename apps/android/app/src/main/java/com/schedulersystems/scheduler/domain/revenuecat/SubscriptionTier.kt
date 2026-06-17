package com.schedulersystems.scheduler.domain.revenuecat

enum class SubscriptionTier(
    val displayName: String,
    val stations: Int,
    val employees: Int,
    val priceMonthly: String,
    val priceYearly: String,
    val features: List<String>
) {
    FREE(
        displayName = "Free",
        stations = 1,
        employees = 3,
        priceMonthly = "$0",
        priceYearly = "$0",
        features = listOf(
            "1 station",
            "Up to 3 employees",
            "Basic schedule building",
            "Priority submission",
        )
    ),
    ESSENTIALS(
        displayName = "Essentials",
        stations = 3,
        employees = 10,
        priceMonthly = "$9.99",
        priceYearly = "$99.99",
        features = listOf(
            "3 stations",
            "Up to 10 employees",
            "Advanced schedule building",
            "Priority submission",
            "Calendar export",
            "Chat support",
        )
    ),
    PRO(
        displayName = "Pro",
        stations = 5,
        employees = 20,
        priceMonthly = "$19.99",
        priceYearly = "$199.99",
        features = listOf(
            "5 stations",
            "Up to 20 employees",
            "All scheduling features",
            "Priority submission",
            "Calendar export",
            "Chat support",
            "AI schedule suggestions",
            "Attendance tracking",
        )
    ),
    ENTERPRISE(
        displayName = "Enterprise",
        stations = Int.MAX_VALUE,
        employees = Int.MAX_VALUE,
        priceMonthly = "Custom",
        priceYearly = "Custom",
        features = listOf(
            "Unlimited stations",
            "Unlimited employees",
            "All Pro features",
            "Priority support",
            "Custom integrations",
            "Dedicated account manager",
        )
    );

    fun isUnlimited(): Boolean = stations == Int.MAX_VALUE
}

data class TierConfig(
    val tier: SubscriptionTier,
    val stations: Int = tier.stations,
    val employees: Int = tier.employees,
    val priceMonthly: String = tier.priceMonthly,
    val priceYearly: String = tier.priceYearly,
    val features: List<String> = tier.features
)
