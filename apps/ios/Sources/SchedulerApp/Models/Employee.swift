import Foundation

struct Employee: Identifiable, Codable, Hashable {
    let id: String
    let tenantId: String
    let userId: String
    let displayName: String
    let email: String
    let phone: String?
    let role: EmployeeRole
    let stations: [String]
    let isActive: Bool
    let createdAt: Date
}

enum EmployeeRole: String, Codable {
    case worker
    case manager
    case admin
}
