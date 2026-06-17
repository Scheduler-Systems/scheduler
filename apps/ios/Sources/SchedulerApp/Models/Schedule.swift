import Foundation

struct Schedule: Identifiable, Codable, Hashable {
    let id: String
    let tenantId: String
    let name: String
    let startDate: Date
    let endDate: Date
    let shifts: [Shift]
    let status: ScheduleStatus
    let createdAt: Date
    let updatedAt: Date
}

struct Shift: Identifiable, Codable, Hashable {
    let id: String
    let scheduleId: String
    var dayOfWeek: DayOfWeek
    var startTime: String
    var endTime: String
    let assignedWorkerId: String?
    let stationId: String?
    let notes: String?
}

enum DayOfWeek: String, Codable, CaseIterable {
    case monday, tuesday, wednesday, thursday, friday, saturday, sunday
}

enum ScheduleStatus: String, Codable {
    case draft
    case published
    case archived
}
