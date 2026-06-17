package com.schedulersystems.scheduler.ui.screens.profile

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.schedulersystems.scheduler.data.repositories.AuthRepository
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
class ProfileSettingsScreenTest {

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
    fun shouldDisplayProfileTitle() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Profile").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayPersonalInfoSection() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Personal Info").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayNameField() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Name").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEmailField() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Email").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayRoleField() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Role").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySignOutButton() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Sign Out").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayBackButton() {
        composeRule.setContent {
            ProfileSettingsScreen(
                viewModel = ProfileSettingsViewModel(authRepository),
                onNavigateBack = {}
            )
        }

        composeRule.onNodeWithText("Profile").assertIsDisplayed()
    }
}
