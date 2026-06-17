package com.schedulersystems.scheduler.ui.screens.onboarding

import android.content.Context
import android.content.SharedPreferences
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.navigation.compose.ComposeNavigator
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.testing.TestNavHostController
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class OnboardingScreenTest {

    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var navController: TestNavHostController
    private lateinit var context: Context

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        navController = TestNavHostController(context)
        navController.navigatorProvider.addNavigator(ComposeNavigator())
    }

    @Test
    fun shouldDisplayFirstSlideTitle() {
        composeRule.setContent {
            NavHost(navController = navController, startDestination = "onboarding") {
                composable("onboarding") {
                    OnboardingScreen(navController = navController)
                }
                composable("login") { }
            }
        }

        composeRule.onNodeWithText("Stay Connected").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayStartNowButton() {
        composeRule.setContent {
            NavHost(navController = navController, startDestination = "onboarding") {
                composable("onboarding") {
                    OnboardingScreen(navController = navController)
                }
                composable("login") { }
            }
        }

        composeRule.onNodeWithText("Start Now").assertIsDisplayed()
    }

    @Test
    fun shouldSetOnboardingCompletedInSharedPreferencesOnButtonClick() {
        composeRule.setContent {
            NavHost(navController = navController, startDestination = "onboarding") {
                composable("onboarding") {
                    OnboardingScreen(navController = navController)
                }
                composable("login") { }
            }
        }

        composeRule.onNodeWithText("Start Now").performClick()

        val prefs: SharedPreferences = context.getSharedPreferences("scheduler_prefs", Context.MODE_PRIVATE)
        assertTrue(prefs.getBoolean("onboarding_completed", false))
    }
}
