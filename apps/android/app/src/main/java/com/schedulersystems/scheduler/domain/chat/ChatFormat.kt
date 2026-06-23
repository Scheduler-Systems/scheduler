package com.schedulersystems.scheduler.domain.chat

/**
 * Pure chat display rules shared by the chat list/detail screens (parity with the Flutter/web
 * chat). Kept framework-free so they're JVM-unit-testable; the screens read Firestore directly.
 */

/** A thread is unread for me when my user ref is NOT in last_message_seen_by. */
fun chatUnread(seenByUserIds: List<String>, myUserId: String): Boolean =
    !seenByUserIds.contains(myUserId)

/** Thread title: a schedule/group chat uses the schedule name; a 1:1 uses the other participant. */
fun chatTitle(otherParticipantName: String?, scheduleName: String?): String {
    val schedule = scheduleName?.trim().orEmpty()
    if (schedule.isNotEmpty()) return "$schedule - Group Chat"
    val other = otherParticipantName?.trim().orEmpty()
    return other.ifEmpty { "Chat" }
}
