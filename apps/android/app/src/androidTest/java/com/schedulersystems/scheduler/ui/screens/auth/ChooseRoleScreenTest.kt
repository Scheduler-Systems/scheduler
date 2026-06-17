package com.schedulersystems.scheduler.ui.screens.auth

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
class ChooseRoleScreenTest {

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
    fun shouldDisplayChooseYourRoleTitle() {
        composeRule.setContent {
            ChooseRoleScreen(
                onNavigateToHome = {},
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Choose Your Role").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayContinueToHomeButton() {
        composeRule.setContent {
            ChooseRoleScreen(
                onNavigateToHome = {},
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Continue to Home").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayBackButton() {
        composeRule.setContent {
            ChooseRoleScreen(
                onNavigateToHome = {},
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Back").assertIsDisplayed()
    }

    @Test
    fun shouldNavigateToHomeOnContinueClick() {
        var navigatedToHome = false
        composeRule.setContent {
            ChooseRoleScreen(
                onNavigateToHome = { navigatedToHome = true },
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Continue to Home").performClick()
        assertTrue(navigatedToHome)
    }

    @Test
    fun shouldNavigateBackOnBackClick() {
        var navigatedBack = false
        composeRule.setContent {
            ChooseRoleScreen(
                onNavigateToHome = {},
                onNavigateBack = { navigatedBack = true }
            )
        }

        composeRule.onNodeWithText("Back").performClick()
        assertTrue(navigatedBack)
    }
}
