import Foundation

// A schedule invitation (manager invited an employee to a schedule).
struct Invitation: Identifiable, Hashable {
    let id: String
    let scheduleName: String
    let invitee: String
    let status: String

    // "ADD_RQUEST_PENDING" (the preserved Flutter typo) etc. → a friendly label.
    var statusLabel: String {
        if status.hasSuffix("PENDING") { return "Pending" }
        if status.hasSuffix("ACCEPTED") { return "Accepted" }
        if status.hasSuffix("DECLINED") { return "Declined" }
        return status
    }
}
