@file:OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)

package com.schedulersystems.scheduler.ui.screens.notifications

import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.SchedulerApiService
import com.schedulersystems.scheduler.data.network.dto.NotificationDto
import com.schedulersystems.scheduler.data.network.dto.NotificationListResponse
import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.User
import io.mockk.coEvery
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
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import retrofit2.Response

class NotificationsViewModelTest {

    private val testDispatcher = StandardTestDispatcher()
    private lateinit var api: SchedulerApi
    private lateinit var service: SchedulerApiService
    private lateinit var authRepository: AuthRepository

    @Before
    fun setup() {
        Dispatchers.setMain(testDispatcher)
        api = mockk()
        service = mockk()
        authRepository = mockk()
        every { api.service } returns service
        every { authRepository.currentUser } returns
            flowOf(User("u1", "u@x.com", null, "U", Role.EMPLOYEE, false, null))
    }

    @After
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun `load populates the feed from the api and counts unread`() = runTest {
        coEvery { service.listNotifications(any()) } returns Response.success(
            NotificationListResponse(
                items = listOf(
                    NotificationDto(id = "1", content = "Published", type = "SYSTEM", isRead = false),
                    NotificationDto(id = "2", content = "Read one", type = "SYSTEM", isRead = true)
                )
            )
        )
        val vm = NotificationsViewModel(api, authRepository)
        advanceUntilIdle()

        val s = vm.state.value
        assertFalse(s.isLoading)
        assertEquals(2, s.notifications.size)
        assertEquals(1, s.unreadCount)
        assertEquals("Published", s.notifications[0].content)
    }

    @Test
    fun `markAsRead marks the notification and decrements unread`() = runTest {
        coEvery { service.listNotifications(any()) } returns Response.success(
            NotificationListResponse(items = listOf(NotificationDto(id = "1", content = "A", type = "SYSTEM", isRead = false)))
        )
        val vm = NotificationsViewModel(api, authRepository)
        advanceUntilIdle()

        vm.markAsRead("1")
        assertTrue(vm.state.value.notifications[0].isRead)
        assertEquals(0, vm.state.value.unreadCount)
    }

    @Test
    fun `api failure yields an empty feed, not a crash`() = runTest {
        coEvery { service.listNotifications(any()) } throws RuntimeException("network down")
        val vm = NotificationsViewModel(api, authRepository)
        advanceUntilIdle()

        assertFalse(vm.state.value.isLoading)
        assertTrue(vm.state.value.notifications.isEmpty())
    }
}
