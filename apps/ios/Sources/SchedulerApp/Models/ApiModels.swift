import Foundation

struct ScheduleResponse: Decodable {
    let id: String
    let tenantId: String
    let name: String
    let settings: [String: String]?
    let status: String
    let createdBy: String?
    let createdAt: String?
    let updatedAt: String?
}

struct CreateScheduleRequest: Encodable {
    let name: String
    let settings: [String: String]?
    let status: String?

    init(name: String, settings: [String: String]? = nil, status: String? = "draft") {
        self.name = name
        self.settings = settings
        self.status = status
    }
}

struct UpdateScheduleRequest: Encodable {
    let updates: ScheduleUpdates
}

struct ScheduleUpdates: Encodable {
    let name: String?
    let settings: [String: String]?
    let status: String?
}

struct DeleteResponse: Decodable {
    let success: Bool
    let id: String
}

struct AvailabilityRequest: Encodable {
    let availability: [String: String]
}

struct AvailabilityResponse: Decodable {
    let id: String
    let tenantId: String
    let scheduleId: String
    let userId: String
    let availability: [String: String]?
    let state: String
    let createdAt: String?
}

struct DraftRequest: Encodable {
    let shifts: [ShiftPayload]
}

struct ShiftPayload: Codable {
    let dayOfWeek: String
    let startTime: String
    let endTime: String
    let assignedWorkerId: String?
}

struct DraftResponse: Decodable {
    let id: String
    let tenantId: String
    let scheduleId: String
    let shifts: [ShiftPayload]?
    let createdBy: String
    let createdAt: String?
}

struct PublishRequest: Encodable {
    let draftId: String
}

struct PublishResponse: Decodable {
    let id: String
    let tenantId: String
    let scheduleId: String
    let draftId: String
    let publishedAt: String?
}

struct ScheduleRequest: Encodable {
    let type: String
    let details: [String: String]?
}

struct ScheduleRequestResponse: Decodable {
    let id: String
    let tenantId: String
    let scheduleId: String
    let userId: String
    let type: String
    let details: [String: String]?
    let state: String
    let createdAt: String?
}
