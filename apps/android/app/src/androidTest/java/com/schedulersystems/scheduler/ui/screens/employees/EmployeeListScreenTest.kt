package com.schedulersystems.scheduler.ui.screens.employees

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
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
class EmployeeListScreenTest {

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
    fun shouldDisplayEmployeeListTitle() {
        composeRule.setContent {
            EmployeeListScreen(
                scheduleId = "sched-1",
                viewModel = EmployeeListViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Employees").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEmployeeListWithScheduleNameAndCount() {
        composeRule.setContent {
            EmployeeListScreen(
                scheduleId = "sched-1",
                viewModel = EmployeeListViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Test Schedule").assertIsDisplayed()
        composeRule.onNodeWithText("1 employees").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEmployeeDetails() {
        composeRule.setContent {
            EmployeeListScreen(
                scheduleId = "sched-1",
                viewModel = EmployeeListViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Test Employee").assertIsDisplayed()
        composeRule.onNodeWithText("emp@example.com").assertIsDisplayed()
    }

    @Test
    fun shouldShowEmptyStateWhenScheduleNotFound() {
        composeRule.setContent {
            EmployeeListScreen(
                scheduleId = "nonexistent-id",
                viewModel = EmployeeListViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("No employees added").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayAddEmployeeButton() {
        composeRule.setContent {
            EmployeeListScreen(
                scheduleId = "sched-1",
                viewModel = EmployeeListViewModel(scheduleRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithContentDescription("Add").assertIsDisplayed()
    }
}
