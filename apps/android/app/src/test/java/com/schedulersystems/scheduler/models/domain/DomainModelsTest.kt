package com.schedulersystems.scheduler.models.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class DomainModelsTest {

    @Test
    fun `User can be created with all fields`() {
        val user = User(
            id = "u1",
            email = "test@test.com",
            phone = "123",
            displayName = "Test User",
            role = Role.EMPLOYER,
            isPremium = true,
            tenantId = "t1"
        )
        assertEquals("u1", user.id)
        assertEquals("test@test.com", user.email)
        assertEquals("123", user.phone)
        assertEquals("Test User", user.displayName)
        assertEquals(Role.EMPLOYER, user.role)
        assertTrue(user.isPremium)
        assertEquals("t1", user.tenantId)
    }

    @Test
    fun `User can be created with null fields`() {
        val user = User(
            id = "u1",
            email = null,
            phone = null,
            displayName = null,
            role = null,
            isPremium = false,
            tenantId = null
        )
        assertNull(user.email)
        assertNull(user.role)
    }

    @Test
    fun `Schedule can be created with all fields`() {
        val now = Instant.now()
        val schedule = Schedule(
            id = "s1",
            name = "Test",
            tenantId = "t1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = ScheduleSettings(null, EnabledShifts(false, false, false), "UTC"),
            nextSchedule = emptyList(),
            createdAt = now,
            updatedAt = now
        )
        assertEquals("s1", schedule.id)
        assertEquals("Test", schedule.name)
    }

    @Test
    fun `Employee can be created`() {
        val emp = Employee(
            id = "e1",
            name = "Alice",
            email = "alice@test.com",
            phone = "555",
            role = Role.EMPLOYEE,
            priorityMap = mapOf("d1" to 1)
        )
        assertEquals("e1", emp.id)
        assertEquals("Alice", emp.name)
        assertEquals(Role.EMPLOYEE, emp.role)
    }

    @Test
    fun `Shift can be created`() {
        val shift = Shift(
            day = "Monday",
            startTime = java.time.LocalTime.of(8, 0),
            endTime = java.time.LocalTime.of(16, 0),
            assignedWorker = "Alice"
        )
        assertEquals("Monday", shift.day)
        assertEquals("Alice", shift.assignedWorker)
    }

    @Test
    fun `ShiftRow wraps shifts`() {
        val row = ShiftRow(
            shifts = listOf(
                Shift("Monday", java.time.LocalTime.of(8, 0), java.time.LocalTime.of(16, 0), "Alice")
            )
        )
        assertEquals(1, row.shifts.size)
    }

    @Test
    fun `ScheduleSettings can be created`() {
        val settings = ScheduleSettings(
            submissionDeadline = SubmissionDeadline(enabled = true, deadline = Instant.now()),
            enabledShifts = EnabledShifts(true, false, true),
            timezone = "America/Chicago"
        )
        assertEquals(true, settings.submissionDeadline?.enabled)
        assertEquals(true, settings.enabledShifts.mornings)
        assertEquals(false, settings.enabledShifts.afternoons)
    }

    @Test
    fun `ScheduleSettings with null deadline`() {
        val settings = ScheduleSettings(
            submissionDeadline = null,
            enabledShifts = EnabledShifts(false, false, false),
            timezone = "UTC"
        )
        assertNull(settings.submissionDeadline)
    }

    @Test
    fun `Role enum has three values`() {
        assertEquals(3, Role.entries.size)
        assertEquals(Role.EMPLOYER, Role.valueOf("EMPLOYER"))
        assertEquals(Role.EMPLOYEE, Role.valueOf("EMPLOYEE"))
        assertEquals(Role.ADMIN, Role.valueOf("ADMIN"))
    }

    @Test
    fun `ScheduleRequest can be created`() {
        val now = Instant.now()
        val req = ScheduleRequest(
            id = "r1",
            scheduleName = "Test Schedule",
            scheduleRef = "ref-1",
            fromUser = "user1",
            toUser = "user2",
            toUserIdentification = "user2@test.com",
            isAddRequest = true,
            isJoinRequest = false,
            requestStatus = RequestStatus.ADD_REQUEST_PENDING,
            isRead = false,
            createdTime = now
        )
        assertEquals("r1", req.id)
        assertEquals(RequestStatus.ADD_REQUEST_PENDING, req.requestStatus)
        assertTrue(req.isAddRequest)
        assertFalse(req.isJoinRequest)
    }

    @Test
    fun `RequestStatus enum has five values`() {
        assertEquals(5, RequestStatus.entries.size)
        assertEquals(RequestStatus.ADD_REQUEST_PENDING, RequestStatus.valueOf("ADD_REQUEST_PENDING"))
        assertEquals(RequestStatus.JOIN_REQUEST_PENDING, RequestStatus.valueOf("JOIN_REQUEST_PENDING"))
        assertEquals(RequestStatus.APPROVED, RequestStatus.valueOf("APPROVED"))
        assertEquals(RequestStatus.DECLINED, RequestStatus.valueOf("DECLINED"))
        assertEquals(RequestStatus.EXPIRED, RequestStatus.valueOf("EXPIRED"))
    }

    @Test
    fun `BuiltSchedule can be created`() {
        val now = Instant.now()
        val bs = BuiltSchedule(
            id = "bs1",
            schedule = listOf(listOf(listOf("Alice"))),
            firstWeekday = "Sunday",
            lastWeekday = "Saturday",
            currentPriorities = listOf("Alice"),
            firstWeekdayDatetime = now,
            lastWeekdayDatetime = now,
            timeCreated = now
        )
        assertEquals("bs1", bs.id)
        assertEquals("Sunday", bs.firstWeekday)
        assertEquals(1, bs.currentPriorities.size)
    }

    @Test
    fun `ShiftRequest can be created`() {
        val now = Instant.now()
        val sr = ShiftRequest(
            id = "sr1",
            requestingEmployee = "Alice",
            shiftToChangeFrom = now,
            shiftToChangeTo = now,
            builtScheduleRef = "bs1",
            status = ShiftRequestStatus.PENDING,
            createdTime = now
        )
        assertEquals("sr1", sr.id)
        assertEquals("Alice", sr.requestingEmployee)
        assertEquals(ShiftRequestStatus.PENDING, sr.status)
    }

    @Test
    fun `ShiftRequestStatus enum has three values`() {
        assertEquals(3, ShiftRequestStatus.entries.size)
        assertEquals(ShiftRequestStatus.PENDING, ShiftRequestStatus.valueOf("PENDING"))
        assertEquals(ShiftRequestStatus.APPROVED, ShiftRequestStatus.valueOf("APPROVED"))
        assertEquals(ShiftRequestStatus.DECLINED, ShiftRequestStatus.valueOf("DECLINED"))
    }

    @Test
    fun `Notification can be created`() {
        val now = Instant.now()
        val notif = Notification(
            id = "n1",
            isRead = false,
            fromUser = "user1",
            toUser = "user2",
            content = "Hello",
            type = NotificationType.CHAT_MESSAGE,
            chatRefId = "chat1",
            timeCreated = now
        )
        assertEquals("n1", notif.id)
        assertFalse(notif.isRead)
        assertEquals(NotificationType.CHAT_MESSAGE, notif.type)
    }

    @Test
    fun `NotificationType enum has five values`() {
        assertEquals(5, NotificationType.entries.size)
        assertEquals(NotificationType.CHAT_MESSAGE, NotificationType.valueOf("CHAT_MESSAGE"))
        assertEquals(NotificationType.SCHEDULE_REQUEST, NotificationType.valueOf("SCHEDULE_REQUEST"))
        assertEquals(NotificationType.SCHEDULE_CHANGE, NotificationType.valueOf("SCHEDULE_CHANGE"))
        assertEquals(NotificationType.SHIFT_CHANGE, NotificationType.valueOf("SHIFT_CHANGE"))
        assertEquals(NotificationType.SYSTEM, NotificationType.valueOf("SYSTEM"))
    }

    @Test
    fun `Chat can be created`() {
        val chat = Chat(
            id = "c1",
            users = listOf("u1", "u2"),
            userA = "u1",
            userB = "u2",
            lastMessage = "Hi",
            lastMessageTime = Instant.now(),
            lastMessageSentBy = "u1",
            lastMessageSeenBy = listOf("u2"),
            groupChatId = 0,
            scheduleRef = "s1"
        )
        assertEquals("c1", chat.id)
        assertEquals(2, chat.users.size)
        assertEquals("Hi", chat.lastMessage)
    }

    @Test
    fun `ChatMessage can be created`() {
        val now = Instant.now()
        val msg = ChatMessage(
            id = "m1",
            chatRef = "c1",
            sender = "u1",
            content = "Hello World",
            timestamp = now,
            isRead = false
        )
        assertEquals("m1", msg.id)
        assertEquals("Hello World", msg.content)
        assertFalse(msg.isRead)
    }

    @Test
    fun `EnabledShifts can be created`() {
        val es = EnabledShifts(mornings = true, afternoons = true, evenings = false)
        assertTrue(es.mornings)
        assertTrue(es.afternoons)
        assertFalse(es.evenings)
    }
}
