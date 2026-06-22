package com.schedulersystems.scheduler.data.network.dto

import org.junit.Assert.assertEquals
import org.junit.Test

// Role mapping for the choose-role auth step: manager → creator+admin (not worker),
// employee → worker (parity with scheduler-web's roleStructToFlutterString + iOS).
class UserProfileDtoTest {

    @Test
    fun `manager maps to creator and admin, not worker`() {
        val r = roleStructFor(isManager = true)
        assertEquals(true, r.isCreator)
        assertEquals(true, r.isAdmin)
        assertEquals(false, r.isWorker)
    }

    @Test
    fun `employee maps to worker only`() {
        val r = roleStructFor(isManager = false)
        assertEquals(false, r.isCreator)
        assertEquals(false, r.isAdmin)
        assertEquals(true, r.isWorker)
    }
}
