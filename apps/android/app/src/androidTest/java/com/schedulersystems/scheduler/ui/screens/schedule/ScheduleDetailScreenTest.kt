package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.schedulersystems.scheduler.data.repositories.AuthRepository
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
class ScheduleDetailScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    @Inject
    lateinit var scheduleRepository: ScheduleRepository

    @Inject
    lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayScheduleNameLabel() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Schedule Name:").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayScheduleNameInContent() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onAllNodesWithText("Test Schedule").assertCountEquals(2)
    }

    @Test
    fun shouldDisplayStatisticsSection() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Statistics").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEmployeeListButton() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Employee List & Add Requests").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySubmitPrioritiesButton() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Submit Priorities").assertIsDisplayed()
    }

    @Test
    fun shouldClickSubmitPrioritiesButton() {
        composeRule.setContent {
            ScheduleDetailScreen(
                scheduleId = "sched-1",
                viewModel = ScheduleDetailViewModel(scheduleRepository, authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Submit Priorities").performClick()
        composeRule.onNodeWithText("Submit Priorities").assertIsDisplayed()
    }
}
