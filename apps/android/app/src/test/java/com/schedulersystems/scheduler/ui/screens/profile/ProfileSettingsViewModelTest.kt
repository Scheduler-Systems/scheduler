@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.profile

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ProfileSettingsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

    private val testUser = User(
        id = "user-1",
        email = "alice@test.com",
        phone = "+1234567890",
        displayName = "Alice",
        role = Role.EMPLOYEE,
        isPremium = true,
        tenantId = null
    )

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        authRepository = mockk()
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `should start with loading state`() {
        val vm = ProfileSettingsViewModel(authRepository)

        assertTrue(vm.state.value.isLoading)
        assertEquals("", vm.state.value.displayName)
        assertNull(vm.state.value.email)
        assertFalse(vm.state.value.isEditing)
        assertFalse(vm.state.value.isSaving)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should load profile on initialization`() = runTest {
        every { authRepository.currentUser } returns flowOf(testUser)

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals("Alice", vm.state.value.displayName)
        assertEquals("alice@test.com", vm.state.value.email)
        assertEquals("+1234567890", vm.state.value.phone)
        assertEquals("EMPLOYEE", vm.state.value.role)
        assertTrue(vm.state.value.isPremium)
    }

    @Test
    fun `should handle null user when loading profile`() = runTest {
        every { authRepository.currentUser } returns flowOf(null)

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals("", vm.state.value.displayName)
        assertNull(vm.state.value.email)
        assertNull(vm.state.value.phone)
        assertNull(vm.state.value.role)
        assertFalse(vm.state.value.isPremium)
    }

    @Test
    fun `should enter editing mode with current display name`() = runTest {
        every { authRepository.currentUser } returns flowOf(testUser)

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()
        vm.startEditing()

        assertTrue(vm.state.value.isEditing)
        assertEquals("Alice", vm.state.value.editName)
    }

    @Test
    fun `should cancel editing and clear edit name`() {
        every { authRepository.currentUser } returns flowOf(testUser)

        val vm = ProfileSettingsViewModel(authRepository)
        vm.startEditing()
        vm.setEditName("New Name")
        vm.cancelEditing()

        assertFalse(vm.state.value.isEditing)
        assertEquals("", vm.state.value.editName)
    }

    @Test
    fun `should update edit name on setEditName`() {
        every { authRepository.currentUser } returns flowOf(testUser)

        val vm = ProfileSettingsViewModel(authRepository)
        vm.startEditing()
        vm.setEditName("Alice Updated")

        assertEquals("Alice Updated", vm.state.value.editName)
    }

    @Test
    fun `should save profile successfully`() = runTest {
        every { authRepository.currentUser } returns flowOf(testUser)
        coEvery { authRepository.updateUserProfile("Alice Updated") } returns Result.success(Unit)

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()
        vm.startEditing()
        vm.setEditName("Alice Updated")
        vm.saveProfile()
        advanceUntilIdle()

        assertFalse(vm.state.value.isSaving)
        assertTrue(vm.state.value.isSaved)
        assertFalse(vm.state.value.isEditing)
        assertEquals("Alice Updated", vm.state.value.displayName)
        assertNull(vm.state.value.error)
    }

    @Test
    fun `should show error on save profile failure`() = runTest {
        every { authRepository.currentUser } returns flowOf(testUser)
        coEvery { authRepository.updateUserProfile("Alice") } returns
            Result.failure(Exception("Update failed"))

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()
        vm.startEditing()
        vm.saveProfile()
        advanceUntilIdle()

        assertFalse(vm.state.value.isSaving)
        assertFalse(vm.state.value.isSaved)
        assertTrue(vm.state.value.isEditing)
        assertEquals("Update failed", vm.state.value.error)
    }

    @Test
    fun `should call signOut on repository`() = runTest {
        every { authRepository.currentUser } returns flowOf(testUser)
        coEvery { authRepository.signOut() } returns Result.success(Unit)

        val vm = ProfileSettingsViewModel(authRepository)
        advanceUntilIdle()

        vm.signOut()
        advanceUntilIdle()

        coVerify { authRepository.signOut() }
    }
}
