@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.chat

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import io.mockk.mockk
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ChatViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var authRepository: AuthRepository

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
    fun `should start with loading state`() = runTest {
        val vm = ChatViewModel(authRepository)

        assertFalse(vm.state.value.isLoading)
        assertTrue(vm.state.value.chats.isEmpty())
    }

    @Test
    fun `should load chat list after initialization`() = runTest {
        val vm = ChatViewModel(authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals(3, vm.state.value.chats.size)
    }

    @Test
    fun `should populate sample chats with correct data`() = runTest {
        val vm = ChatViewModel(authRepository)
        advanceUntilIdle()

        val chats = vm.state.value.chats
        assertEquals("Team Alpha", chats[0].name)
        assertEquals("Meeting at 3pm?", chats[0].lastMessage)
        assertEquals(2, chats[0].unreadCount)

        assertEquals("John Doe", chats[1].name)
        assertEquals("Thanks!", chats[1].lastMessage)
        assertEquals(0, chats[1].unreadCount)

        assertEquals("Support", chats[2].name)
        assertEquals("How can we help?", chats[2].lastMessage)
        assertEquals(1, chats[2].unreadCount)
    }

    @Test
    fun `should reload chats on explicit loadChats call`() = runTest {
        val vm = ChatViewModel(authRepository)
        advanceUntilIdle()
        assertFalse(vm.state.value.isLoading)
        assertEquals(3, vm.state.value.chats.size)

        vm.loadChats()
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertEquals(3, vm.state.value.chats.size)
    }
}
