package com.schedulersystems.scheduler.models.domain

import java.time.Instant

data class Chat(
    val id: String,
    val users: List<String>,
    val userA: String?,
    val userB: String?,
    val lastMessage: String?,
    val lastMessageTime: Instant?,
    val lastMessageSentBy: String?,
    val lastMessageSeenBy: List<String>,
    val groupChatId: Int,
    val scheduleRef: String?
)

data class ChatMessage(
    val id: String,
    val chatRef: String,
    val sender: String,
    val content: String,
    val timestamp: Instant,
    val isRead: Boolean
)
