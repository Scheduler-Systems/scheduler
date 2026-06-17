package com.schedulersystems.scheduler.domain.revenuecat

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class PaywallScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    private val sampleTierConfigs = listOf(
        TierConfig(tier = SubscriptionTier.FREE),
        TierConfig(tier = SubscriptionTier.ESSENTIALS),
        TierConfig(tier = SubscriptionTier.PRO),
        TierConfig(tier = SubscriptionTier.ENTERPRISE)
    )

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayChooseYourPlanTitle() {
        composeRule.setContent {
            PaywallScreen(
                currentTier = SubscriptionTier.FREE,
                tierConfigs = sampleTierConfigs,
                onUpgradeClick = {},
                onDismiss = {}
            )
        }

        composeRule.onNodeWithText("Choose Your Plan").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayCurrentTierBadge() {
        composeRule.setContent {
            PaywallScreen(
                currentTier = SubscriptionTier.FREE,
                tierConfigs = sampleTierConfigs,
                onUpgradeClick = {},
                onDismiss = {}
            )
        }

        composeRule.onNodeWithText("Current").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayTierNames() {
        composeRule.setContent {
            PaywallScreen(
                currentTier = SubscriptionTier.FREE,
                tierConfigs = sampleTierConfigs,
                onUpgradeClick = {},
                onDismiss = {}
            )
        }

        composeRule.onNodeWithText("Free").assertIsDisplayed()
        composeRule.onNodeWithText("Essentials").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("Pro").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("Enterprise").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun shouldDisplayUpgradeButtonsForNonCurrentTiers() {
        composeRule.setContent {
            PaywallScreen(
                currentTier = SubscriptionTier.FREE,
                tierConfigs = sampleTierConfigs,
                onUpgradeClick = {},
                onDismiss = {}
            )
        }

        composeRule.onAllNodesWithText("Upgrade").assertCountEquals(3)
    }

    @Test
    fun shouldDisplaySubscriptionManagementText() {
        composeRule.setContent {
            PaywallScreen(
                currentTier = SubscriptionTier.FREE,
                tierConfigs = sampleTierConfigs,
                onUpgradeClick = {},
                onDismiss = {}
            )
        }

        composeRule.onNodeWithText("Manage your subscription at any time through RevenueCat.")
            .performScrollTo()
            .assertIsDisplayed()
    }
}
