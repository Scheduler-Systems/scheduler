package com.schedulersystems.scheduler.repositories

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import javax.inject.Inject

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class AuthRepositoryIntegrationTest {

    @get:Rule
    val hiltRule = HiltAndroidRule(this)

    @Inject
    lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldProvideAuthenticatedUser() = runBlocking {
        val user = authRepository.currentUser.first()

        assertTrue(user != null)
        assertEquals("test-id", user?.id)
        assertEquals("test@example.com", user?.email)
        assertEquals("Test User", user?.displayName)
        assertEquals(Role.EMPLOYEE, user?.role)
    }

    @Test
    fun shouldReportAuthenticated() = runBlocking {
        val isAuthenticated = authRepository.isAuthenticated.first()

        assertTrue(isAuthenticated)
    }

    @Test
    fun shouldSignInWithEmail() = runBlocking {
        val result = authRepository.signInWithEmail("test@example.com", "password")

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldSignOut() = runBlocking {
        val result = authRepository.signOut()

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldUpdateUserProfile() = runBlocking {
        val result = authRepository.updateUserProfile("New Name")

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldSendPasswordResetEmail() = runBlocking {
        val result = authRepository.sendPasswordResetEmail("test@example.com")

        assertTrue(result.isSuccess)
    }
}
