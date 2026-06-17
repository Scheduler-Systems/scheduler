package com.schedulersystems.scheduler.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4
import javax.inject.Inject

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class ScheduleSettingsScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    @Inject
    lateinit var scheduleRepository: ScheduleRepository

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayScheduleSettingsTitle() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Schedule Settings").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayScheduleName() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Schedule Name: Test Schedule").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayShiftToggles() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Morning").assertIsDisplayed()
        composeRule.onNodeWithText("Afternoon").assertIsDisplayed()
        composeRule.onNodeWithText("Evening").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEnabledShiftsSection() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Enabled Shifts").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayTimezone() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Current: UTC").assertIsDisplayed()
    }

    @Test
    fun shouldToggleMorningSwitchOff() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onAllNodes(isToggleable())[0].performClick()
        composeRule.onNodeWithText("Save Settings").performScrollTo().performClick()
        composeRule.onNodeWithText("Settings saved successfully!").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySaveSettingsButton() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Save Settings").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun shouldSaveSettingsWhenSaveButtonClicked() {
        composeRule.setContent {
            ScheduleSettingsScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleSettingsViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Save Settings").performScrollTo().performClick()
        composeRule.onNodeWithText("Settings saved successfully!").performScrollTo().assertIsDisplayed()
    }
}
