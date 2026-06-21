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

// Employee embedded in a schedule (schedules/{id}.employees[] on the web/Flutter
// side). The Go API uses snake_case keys mirroring scheduler-web's EmployeeDetails;
// identity is the email. Served from GET .../schedules/{id}/employees as {items:[...]}.
struct EmployeeResponse: Decodable {
    let employeeName: String
    let employeeEmail: String
    let employeePhone: String?
    let role: EmployeeRoleResponse?
    let userRef: String?

    enum CodingKeys: String, CodingKey {
        case employeeName = "employee_name"
        case employeeEmail = "employee_email"
        case employeePhone = "employee_phone"
        case role
        case userRef = "user_ref"
    }
}

struct EmployeeRoleResponse: Decodable {
    let isCreator: Bool?
    let isAdmin: Bool?
    let isWorker: Bool?

    enum CodingKeys: String, CodingKey {
        case isCreator = "is_creator"
        case isAdmin = "is_admin"
        case isWorker = "is_worker"
    }
}

// Add-employee request body (snake_case, role object), mirroring the server's
// employeeInput. is_worker:true matches the server default for invited staff.
struct AddEmployeeRequest: Encodable {
    let employeeName: String
    let employeeEmail: String
    let employeePhone: String
    let role: AddEmployeeRole

    init(name: String, email: String, phone: String) {
        self.employeeName = name
        self.employeeEmail = email
        self.employeePhone = phone
        self.role = AddEmployeeRole(isWorker: true)
    }

    enum CodingKeys: String, CodingKey {
        case employeeName = "employee_name"
        case employeeEmail = "employee_email"
        case employeePhone = "employee_phone"
        case role
    }
}

struct AddEmployeeRole: Encodable {
    let isWorker: Bool
    enum CodingKeys: String, CodingKey {
        case isWorker = "is_worker"
    }
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
