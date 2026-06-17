import Foundation

struct Tenant: Identifiable, Codable {
    let id: String
    let name: String
    let ownerId: String
    let plan: TenantPlan
    let maxEmployees: Int
    let features: [String]
    let createdAt: Date
}

enum TenantPlan: String, Codable {
    case free
    case starter
    case professional
    case enterprise
}
