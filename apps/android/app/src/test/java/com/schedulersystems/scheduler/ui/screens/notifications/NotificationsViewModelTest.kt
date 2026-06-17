@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.notifications

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class NotificationsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `initial state should not be loading with 2 unread out of 3 notifications`() {
        val vm = NotificationsViewModel()
        val state = vm.state.value

        assertFalse(state.isLoading)
        assertEquals(3, state.notifications.size)
        assertEquals(2, state.unreadCount)
    }

    @Test
    fun `notifications should include system schedule request and chat types`() {
        val vm = NotificationsViewModel()
        val state = vm.state.value

        assertEquals("system", state.notifications[0].fromUser)
        assertEquals("John", state.notifications[1].fromUser)
        assertEquals("Team Alpha", state.notifications[2].fromUser)
        assertEquals(
            "Your schedule for next week has been published",
            state.notifications[0].content
        )
    }

    @Test
    fun `markAsRead should mark the notification and decrease unread count`() {
        val vm = NotificationsViewModel()

        vm.markAsRead("1")

        val state = vm.state.value
        assertTrue(state.notifications[0].isRead)
        assertEquals(1, state.unreadCount)
    }

    @Test
    fun `markAsRead on already read notification should not change unread count`() {
        val vm = NotificationsViewModel()

        vm.markAsRead("3")

        val state = vm.state.value
        assertTrue(state.notifications[2].isRead)
        assertEquals(2, state.unreadCount)
    }

    @Test
    fun `markAsRead with unknown id should not mutate state`() {
        val vm = NotificationsViewModel()

        vm.markAsRead("non-existent-id")

        val state = vm.state.value
        assertEquals(3, state.notifications.size)
        assertEquals(2, state.unreadCount)
    }

    @Test
    fun `unread count should drop to zero after marking both unread notifications as read`() {
        val vm = NotificationsViewModel()

        vm.markAsRead("1")
        vm.markAsRead("2")

        assertEquals(0, vm.state.value.unreadCount)
    }
}
