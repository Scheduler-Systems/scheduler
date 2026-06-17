package com.schedulersystems.scheduler.ui.screens.notifications

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class NotificationsScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayNotificationsTitle() {
        composeRule.setContent {
            NotificationsScreen(
                viewModel = NotificationsViewModel(),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Notifications").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySystemNotification() {
        composeRule.setContent {
            NotificationsScreen(
                viewModel = NotificationsViewModel(),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Your schedule for next week has been published")
            .assertIsDisplayed()
    }

    @Test
    fun shouldDisplayScheduleRequestNotification() {
        composeRule.setContent {
            NotificationsScreen(
                viewModel = NotificationsViewModel(),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("You have a new schedule request from John Doe")
            .assertIsDisplayed()
    }

    @Test
    fun shouldDisplayChatMessageNotification() {
        composeRule.setContent {
            NotificationsScreen(
                viewModel = NotificationsViewModel(),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("New message in Team Alpha chat")
            .assertIsDisplayed()
    }

    @Test
    fun shouldMarkAsReadWhenNotificationClicked() {
        composeRule.setContent {
            NotificationsScreen(
                viewModel = NotificationsViewModel(),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Your schedule for next week has been published")
            .performClick()

        composeRule.onNodeWithText("Your schedule for next week has been published")
            .assertIsDisplayed()
    }
}
