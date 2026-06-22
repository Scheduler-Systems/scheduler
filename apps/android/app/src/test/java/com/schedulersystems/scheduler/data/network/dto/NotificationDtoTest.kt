package com.schedulersystems.scheduler.data.network.dto

import com.schedulersystems.scheduler.models.domain.NotificationType
import org.junit.Assert.assertEquals
import org.junit.Test

// The notification feed maps the Go API's camelCase JSON onto the Notification domain model.
class NotificationDtoTest {

    @Test
    fun `maps fields and the type enum`() {
        val dto = NotificationDto(
            id = "n1", userId = "u1", fromUser = "system",
            content = "Your schedule was published", type = "SCHEDULE_CHANGE",
            chatRefId = null, isRead = false, createdAt = "2026-06-22T10:00:00Z"
        )
        val n = dto.toDomain()
        assertEquals("n1", n.id)
        assertEquals("Your schedule was published", n.content)
        assertEquals(NotificationType.SCHEDULE_CHANGE, n.type)
        assertEquals(false, n.isRead)
        assertEquals("u1", n.toUser)
    }

    @Test
    fun `unknown or missing type falls back to SYSTEM`() {
        assertEquals(NotificationType.SYSTEM, NotificationDto(id = "n2", type = "WAT").toDomain().type)
        assertEquals(NotificationType.SYSTEM, NotificationDto(id = "n3", type = null).toDomain().type)
    }
}
