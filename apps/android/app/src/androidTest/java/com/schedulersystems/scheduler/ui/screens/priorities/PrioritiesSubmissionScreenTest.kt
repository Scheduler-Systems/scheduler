package com.schedulersystems.scheduler.ui.screens.priorities

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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
class PrioritiesSubmissionScreenTest {

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
    fun shouldDisplaySubmitPrioritiesTitle() {
        composeRule.setContent {
            PrioritiesSubmissionScreen(
                scheduleId = "test-schedule-id",
                onNavigateBack = {},
                viewModel = PrioritiesViewModel(scheduleRepository, authRepository)
            )
        }

        composeRule.onNodeWithText("Submit Priorities").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayNoPrioritiesWhenEmpty() {
        composeRule.setContent {
            PrioritiesSubmissionScreen(
                scheduleId = "test-schedule-id",
                onNavigateBack = {},
                viewModel = PrioritiesViewModel(scheduleRepository, authRepository)
            )
        }

        composeRule.onNodeWithText("No priorities configured").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySubmitButtonWhenPrioritiesLoaded() {
        composeRule.setContent {
            PrioritiesSubmissionScreen(
                scheduleId = "sched-1",
                onNavigateBack = {},
                viewModel = PrioritiesViewModel(scheduleRepository, authRepository)
            )
        }

        composeRule.onNodeWithText("Submit").assertIsDisplayed()
    }
}
