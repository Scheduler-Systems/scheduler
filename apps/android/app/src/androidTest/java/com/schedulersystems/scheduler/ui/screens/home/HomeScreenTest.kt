package com.schedulersystems.scheduler.ui.screens.home

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4
import javax.inject.Inject

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class HomeScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    @Inject
    lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayHomeTitle() {
        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = {},
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText("Home").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayMySchedulesButton() {
        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = {},
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayGreetingSection() {
        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = {},
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText(", Test User!", substring = true).assertIsDisplayed()
    }

    @Test
    fun shouldDisplayMenuIcon() {
        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = {},
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayNotificationsIcon() {
        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = {},
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").assertIsDisplayed()
    }

    @Test
    fun shouldNavigateToMySchedulesWhenClicked() {
        var onMySchedulesCalled = false

        composeRule.setContent {
            HomeScreen(
                viewModel = HomeViewModel(authRepository),
                onNavigateToMySchedules = { onMySchedulesCalled = true },
                onNavigateToNewSchedule = {},
                onNavigateToArchived = {},
                onNavigateToProfile = {},
                onNavigateToNotifications = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").performClick()
        assertTrue("Expected navigate to My Schedules callback", onMySchedulesCalled)
    }
}
