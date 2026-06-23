package com.schedulersystems.scheduler.domain.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatFormatTest {

    @Test
    fun unreadWhenMyRefNotInSeenBy() {
        assertTrue(chatUnread(listOf("alex"), "me"))
        assertFalse(chatUnread(listOf("alex", "me"), "me"))
        assertTrue(chatUnread(emptyList(), "me"))
    }

    @Test
    fun titleUsesScheduleNameForGroupChat() {
        assertEquals("QA Demo - Group Chat", chatTitle(otherParticipantName = "Alex Worker", scheduleName = "QA Demo"))
    }

    @Test
    fun titleUsesOtherParticipantFor1on1() {
        assertEquals("Alex Worker", chatTitle(otherParticipantName = "Alex Worker", scheduleName = null))
    }

    @Test
    fun titleFallsBackWhenNothingResolves() {
        assertEquals("Chat", chatTitle(otherParticipantName = "", scheduleName = ""))
    }
}
