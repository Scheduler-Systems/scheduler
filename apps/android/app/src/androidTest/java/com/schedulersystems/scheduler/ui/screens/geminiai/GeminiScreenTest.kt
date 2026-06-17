package com.schedulersystems.scheduler.ui.screens.geminiai

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class GeminiScreenTest {

    @get:Rule(order = 0)
    val hiltRule = HiltAndroidRule(this)

    @get:Rule(order = 1)
    val composeRule = createComposeRule()

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldDisplayAiSchedulerTitle() {
        composeRule.setContent {
            GeminiScreen(
                scheduleName = null,
                onNavigateBack = {},
                viewModel = GeminiViewModel()
            )
        }

        composeRule.onNodeWithText("AI Scheduler").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayAskGeminiSection() {
        composeRule.setContent {
            GeminiScreen(
                scheduleName = null,
                onNavigateBack = {},
                viewModel = GeminiViewModel()
            )
        }

        composeRule.onNodeWithText("Ask Gemini").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayGenerateButton() {
        composeRule.setContent {
            GeminiScreen(
                scheduleName = null,
                onNavigateBack = {},
                viewModel = GeminiViewModel()
            )
        }

        composeRule.onNodeWithText("Generate").assertIsDisplayed()
    }
}
