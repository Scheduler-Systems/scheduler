package com.schedulersystems.scheduler.ui.screens.auth

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import androidx.test.ext.junit.runners.AndroidJUnit4

@RunWith(AndroidJUnit4::class)
class CreateAccountScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun shouldDisplayCreateAccountTitle() {
        composeRule.setContent {
            CreateAccountScreen(
                onNavigateBack = {},
                onNavigateToHome = {}
            )
        }

        composeRule.onNodeWithText("Create Account").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayBackButton() {
        composeRule.setContent {
            CreateAccountScreen(
                onNavigateBack = {},
                onNavigateToHome = {}
            )
        }

        composeRule.onNodeWithText("Back").assertIsDisplayed()
    }
}
