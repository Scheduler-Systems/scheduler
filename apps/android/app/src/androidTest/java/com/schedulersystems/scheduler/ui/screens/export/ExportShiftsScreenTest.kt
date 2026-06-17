package com.schedulersystems.scheduler.ui.screens.export

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
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
class ExportShiftsScreenTest {

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
    fun shouldDisplayExportShiftsTitle() {
        composeRule.setContent {
            ExportShiftsScreen(
                scheduleId = "test-schedule-id",
                onNavigateBack = {},
                viewModel = ExportShiftsViewModel(scheduleRepository)
            )
        }

        composeRule.onNodeWithText("Export Shifts").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayExportToGoogleCalendarButton() {
        composeRule.setContent {
            ExportShiftsScreen(
                scheduleId = "sched-1",
                onNavigateBack = {},
                viewModel = ExportShiftsViewModel(scheduleRepository)
            )
        }

        composeRule.onNodeWithText("Export to Google Calendar").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayGoogleCalendarSection() {
        composeRule.setContent {
            ExportShiftsScreen(
                scheduleId = "sched-1",
                onNavigateBack = {},
                viewModel = ExportShiftsViewModel(scheduleRepository)
            )
        }

        composeRule.onNodeWithText("Google Calendar").assertIsDisplayed()
    }
}
