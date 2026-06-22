package com.schedulersystems.scheduler.data.network.dto

import com.schedulersystems.scheduler.models.domain.RequestStatus
import org.junit.Assert.assertEquals
import org.junit.Test

class InvitationDtoTest {

    @Test
    fun `toDomain maps fields and the preserved-typo pending status`() {
        val dto = InvitationDto(
            id = "inv1",
            scheduleId = "s1",
            scheduleName = "QA Demo Schedule",
            toUserIdentification = "invitee@example.com",
            isAddRequest = true,
            status = "ADD_RQUEST_PENDING"   // note the preserved Flutter typo
        )
        val req = dto.toDomain()
        assertEquals("inv1", req.id)
        assertEquals("invitee@example.com", req.toUserIdentification)
        assertEquals("QA Demo Schedule", req.scheduleName)
        assertEquals(RequestStatus.ADD_REQUEST_PENDING, req.requestStatus)
    }

    @Test
    fun `toDomain maps accepted and declined`() {
        assertEquals(RequestStatus.APPROVED,
            InvitationDto(id = "a", status = "ADD_REQUEST_ACCEPTED").toDomain().requestStatus)
        assertEquals(RequestStatus.DECLINED,
            InvitationDto(id = "d", status = "ADD_REQUEST_DECLINED").toDomain().requestStatus)
    }

    @Test
    fun `toDomain tolerates nulls`() {
        val req = InvitationDto(id = "x").toDomain()
        assertEquals("", req.toUserIdentification)
        assertEquals(RequestStatus.ADD_REQUEST_PENDING, req.requestStatus)
    }
}
