import XCTest
@testable import SchedulerApp

/// Mirrors Android ChatFormatTest so the chat display rules are faithful across platforms.
final class ChatFormatTests: XCTestCase {

    func testChatUnreadWhenMyRefNotInSeenBy() {
        XCTAssertTrue(chatUnread(seenByUserIds: ["alex"], myUserId: "me"))
        XCTAssertFalse(chatUnread(seenByUserIds: ["alex", "me"], myUserId: "me"))
        XCTAssertTrue(chatUnread(seenByUserIds: [], myUserId: "me"))
    }

    func testChatTitleGroupChatUsesScheduleName() {
        XCTAssertEqual(chatTitle(otherParticipantName: "Alex Worker", scheduleName: "QA Demo"), "QA Demo - Group Chat")
    }

    func testChatTitleOneOnOneUsesOtherParticipant() {
        XCTAssertEqual(chatTitle(otherParticipantName: "Alex Worker", scheduleName: nil), "Alex Worker")
    }

    func testChatTitleFallsBack() {
        XCTAssertEqual(chatTitle(otherParticipantName: "", scheduleName: ""), "Chat")
    }
}
