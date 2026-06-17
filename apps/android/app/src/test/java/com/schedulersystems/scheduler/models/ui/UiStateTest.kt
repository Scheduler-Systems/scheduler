package com.schedulersystems.scheduler.models.ui

import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class UiStateTest {

    @Test
    fun `HomeUiState defaults`() {
        val state = HomeUiState()
        assertFalse(state.isLoading)
        assertTrue(state.schedules.isEmpty())
        assertNull(state.error)
        assertNull(state.userRole)
        assertNull(state.displayName)
    }

    @Test
    fun `HomeUiState with values`() {
        val state = HomeUiState(
            isLoading = true,
            schedules = listOf(Schedule("s1", "S1", "t1", emptyList(), emptyList(), ScheduleSettings(null, EnabledShifts(false, false, false), "UTC"), emptyList(), Instant.now(), Instant.now())),
            error = "Error",
            userRole = Role.EMPLOYER,
            displayName = "Alice"
        )
        assertTrue(state.isLoading)
        assertEquals(1, state.schedules.size)
        assertEquals("Error", state.error)
        assertEquals(Role.EMPLOYER, state.userRole)
        assertEquals("Alice", state.displayName)
    }

    @Test
    fun `ScheduleBuildUiState defaults`() {
        val state = ScheduleBuildUiState()
        assertNull(state.schedule)
        assertTrue(state.shiftRows.isEmpty())
        assertFalse(state.isSaving)
        assertNull(state.selectedCell)
        assertNull(state.error)
    }

    @Test
    fun `ScheduleBuildUiState with values`() {
        val state = ScheduleBuildUiState(
            isSaving = true,
            selectedCell = Pair(1, 2),
            error = "Build error"
        )
        assertTrue(state.isSaving)
        assertEquals(Pair(1, 2), state.selectedCell)
        assertEquals("Build error", state.error)
    }

    @Test
    fun `EmployeeListUiState defaults`() {
        val state = EmployeeListUiState()
        assertFalse(state.isLoading)
        assertTrue(state.employees.isEmpty())
        assertEquals("", state.scheduleName)
        assertNull(state.error)
    }

    @Test
    fun `EmployeeListUiState with values`() {
        val emp = Employee("e1", "Alice", null, null, Role.EMPLOYEE, emptyMap())
        val state = EmployeeListUiState(
            isLoading = true,
            employees = listOf(emp),
            scheduleName = "S1",
            error = "Load error"
        )
        assertTrue(state.isLoading)
        assertEquals(1, state.employees.size)
        assertEquals("S1", state.scheduleName)
        assertEquals("Load error", state.error)
    }

    @Test
    fun `PrioritiesUiState defaults`() {
        val state = PrioritiesUiState()
        assertFalse(state.isLoading)
        assertTrue(state.priorities.isEmpty())
        assertTrue(state.submittedPriorities.isEmpty())
        assertFalse(state.isSubmitting)
        assertNull(state.error)
    }

    @Test
    fun `PrioritiesUiState with values`() {
        val state = PrioritiesUiState(
            isLoading = true,
            priorities = listOf("P1", "P2"),
            submittedPriorities = listOf("P1"),
            isSubmitting = true,
            error = "Submit error"
        )
        assertEquals(2, state.priorities.size)
        assertEquals(1, state.submittedPriorities.size)
        assertTrue(state.isSubmitting)
    }

    @Test
    fun `ChatUiState defaults`() {
        val state = ChatUiState()
        assertFalse(state.isLoading)
        assertTrue(state.chats.isEmpty())
        assertNull(state.error)
    }

    @Test
    fun `ChatUiState with values`() {
        val state = ChatUiState(
            isLoading = true,
            chats = listOf(ChatItem("c1", "Alice", "Hello", 123L, 2)),
            error = "Chat error"
        )
        assertTrue(state.isLoading)
        assertEquals(1, state.chats.size)
        assertEquals("Chat error", state.error)
    }

    @Test
    fun `ChatItem has correct fields`() {
        val item = ChatItem(
            id = "c1",
            name = "Alice",
            lastMessage = "Hello",
            timestamp = 123456L,
            unreadCount = 5
        )
        assertEquals("c1", item.id)
        assertEquals("Alice", item.name)
        assertEquals("Hello", item.lastMessage)
        assertEquals(123456L, item.timestamp)
        assertEquals(5, item.unreadCount)
    }

    @Test
    fun `ChatItem with null lastMessage`() {
        val item = ChatItem("c1", "Alice", null, 0L, 0)
        assertNull(item.lastMessage)
    }
}
