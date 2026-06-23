import Foundation

/// Pure chat display rules (parity with Android ChatFormat.kt + the Flutter chat). Framework-free
/// so they're unit-testable; the chat views read Firestore directly.

/// A thread is unread for me when my user ref is NOT in last_message_seen_by.
func chatUnread(seenByUserIds: [String], myUserId: String) -> Bool {
    !seenByUserIds.contains(myUserId)
}

/// Thread title: a schedule/group chat uses the schedule name; a 1:1 uses the other participant.
func chatTitle(otherParticipantName: String?, scheduleName: String?) -> String {
    let schedule = (scheduleName ?? "").trimmingCharacters(in: .whitespaces)
    if !schedule.isEmpty { return "\(schedule) - Group Chat" }
    let other = (otherParticipantName ?? "").trimmingCharacters(in: .whitespaces)
    return other.isEmpty ? "Chat" : other
}
