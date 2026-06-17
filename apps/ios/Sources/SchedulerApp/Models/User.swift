import Foundation

struct User: Identifiable, Codable {
    let id: String
    let email: String?
    let displayName: String?
    let photoURL: String?
    let tenantId: String?
    let role: UserRole?
    let isPremium: Bool
    let createdAt: Date?
    let lastLoginAt: Date?
}

enum UserRole: String, Codable {
    case employee
    case manager
    case admin
}

extension User {
    static var anonymous: User {
        User(
            id: "anonymous",
            email: nil,
            displayName: nil,
            photoURL: nil,
            tenantId: nil,
            role: nil,
            isPremium: false,
            createdAt: nil,
            lastLoginAt: nil
        )
    }
}
