package com.schedulersystems.scheduler.ui.screens.onboarding

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.ui.screens.auth.LoginScreen
import com.schedulersystems.scheduler.viewmodels.AuthViewModel
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
class LoginScreenTest {

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
    fun shouldDisplayWelcomeText() {
        composeRule.setContent {
            LoginScreen(
                viewModel = AuthViewModel(authRepository),
                onNavigateToPhoneSignIn = {},
                onNavigateToEmailSignIn = {},
                onNavigateToSignUp = {},
                onNavigateToPasswordReset = {},
                onNavigateToHome = {}
            )
        }

        composeRule.onNodeWithText("Welcome Back").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayEmailAndPasswordFields() {
        composeRule.setContent {
            LoginScreen(
                viewModel = AuthViewModel(authRepository),
                onNavigateToPhoneSignIn = {},
                onNavigateToEmailSignIn = {},
                onNavigateToSignUp = {},
                onNavigateToPasswordReset = {},
                onNavigateToHome = {}
            )
        }

        composeRule.onNodeWithText("Email").assertIsDisplayed()
        composeRule.onNodeWithText("Password").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySignInButton() {
        composeRule.setContent {
            LoginScreen(
                viewModel = AuthViewModel(authRepository),
                onNavigateToPhoneSignIn = {},
                onNavigateToEmailSignIn = {},
                onNavigateToSignUp = {},
                onNavigateToPasswordReset = {},
                onNavigateToHome = {}
            )
        }

        composeRule.onNodeWithText("Sign In").assertIsDisplayed()
    }
}
