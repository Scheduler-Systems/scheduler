package com.schedulersystems.scheduler.ui.screens.auth

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.ui.AuthEvent
import com.schedulersystems.scheduler.viewmodels.AuthViewModel
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
class PhoneSignInScreenTest {

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
    fun shouldDisplaySignInWithPhoneTitle() {
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Sign in with Phone").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayHintText() {
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Enter your phone number to receive a verification code").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayPhoneInputLabel() {
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Phone Number").assertIsDisplayed()
    }

    @Test
    fun shouldDisplaySendVerificationButton() {
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Send Verification Code").assertIsDisplayed()
    }

    @Test
    fun shouldDisplayBackButton() {
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Back").assertIsDisplayed()
    }

    @Test
    fun shouldSendVerificationOnButtonClick() {
        val viewModel = AuthViewModel(authRepository)
        viewModel.onEvent(AuthEvent.PhoneChanged("+1234567890"))

        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = {},
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = viewModel
            )
        }

        composeRule.onNodeWithText("Send Verification Code").performClick()
    }

    @Test
    fun shouldNavigateBackOnBackClick() {
        var navigatedBack = false
        composeRule.setContent {
            PhoneSignInScreen(
                onNavigateBack = { navigatedBack = true },
                onNavigateToPhoneCode = {},
                onNavigateToHome = {},
                viewModel = AuthViewModel(authRepository)
            )
        }

        composeRule.onNodeWithText("Back").performClick()
        assertTrue(navigatedBack)
    }
}
