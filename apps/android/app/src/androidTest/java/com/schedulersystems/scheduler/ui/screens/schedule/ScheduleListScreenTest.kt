package com.schedulersystems.scheduler.ui.screens.schedule

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
class ScheduleListScreenTest {

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
    fun shouldDisplayMySchedulesTitle() {
        composeRule.setContent {
            ScheduleListScreen(
                viewModel = ScheduleListViewModel(scheduleRepository, authRepository),
                onNavigateBack = {},
                onNavigateToScheduleDetail = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayBackButton() {
        composeRule.setContent {
            ScheduleListScreen(
                viewModel = ScheduleListViewModel(scheduleRepository, authRepository),
                onNavigateBack = {},
                onNavigateToScheduleDetail = {}
            )
        }

        composeRule.onNodeWithText("My Schedules").assertIsDisplayed()
    }
}
