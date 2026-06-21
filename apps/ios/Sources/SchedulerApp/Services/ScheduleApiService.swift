import Foundation

protocol ScheduleDataServiceProtocol {
    func fetchSchedules(tenantId: String) async throws -> [Schedule]
    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule
    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee]
    func createSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule
    func updateSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule
    func deleteSchedule(tenantId: String, scheduleId: String) async throws
}

final class ScheduleApiService: ScheduleDataServiceProtocol {
    private let api: ApiClientProtocol

    init(api: ApiClientProtocol) {
        self.api = api
    }

    func fetchSchedules(tenantId: String) async throws -> [Schedule] {
        let items = try await api.fetchSchedules(tenantId: tenantId)
        return items.map { Self.map($0) }
    }

    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule {
        let result = try await api.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
        return Self.map(result)
    }

    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee] {
        let items = try await api.fetchEmployees(tenantId: tenantId, scheduleId: scheduleId)
        return items.map { Self.map($0, tenantId: tenantId) }
    }

    func createSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule {
        let body = CreateScheduleRequest(
            name: schedule.name,
            status: schedule.status.rawValue
        )
        let result = try await api.createSchedule(tenantId: tenantId, body: body)
        return Self.map(result)
    }

    func updateSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule {
        let body = UpdateScheduleRequest(updates: ScheduleUpdates(
            name: schedule.name,
            settings: nil,
            status: schedule.status.rawValue
        ))
        let result = try await api.updateSchedule(tenantId: tenantId, scheduleId: schedule.id, body: body)
        return Self.map(result)
    }

    func deleteSchedule(tenantId: String, scheduleId: String) async throws {
        _ = try await api.deleteSchedule(tenantId: tenantId, scheduleId: scheduleId)
    }

    private static func map(_ response: ScheduleResponse) -> Schedule {
        let status = ScheduleStatus(rawValue: response.status) ?? .draft
        return Schedule(
            id: response.id,
            tenantId: response.tenantId,
            name: response.name,
            startDate: Date(),
            endDate: Date().addingTimeInterval(604800),
            shifts: [],
            status: status,
            createdAt: parseISO(response.createdAt),
            updatedAt: parseISO(response.updatedAt)
        )
    }

    // Maps the API's embedded employee (snake_case, email-as-identity) onto the
    // existing Employee model. id = email (the API's stable identity); fields the
    // embedded record doesn't carry (stations, isActive, createdAt) take sensible
    // defaults — the schedule roster row is a lightweight EmployeeDetails, not the
    // full employees-collection document.
    private static func map(_ response: EmployeeResponse, tenantId: String) -> Employee {
        let role: EmployeeRole
        if response.role?.isAdmin == true {
            role = .admin
        } else if response.role?.isCreator == true {
            role = .manager
        } else {
            role = .worker
        }
        return Employee(
            id: response.employeeEmail,
            tenantId: tenantId,
            userId: response.userRef ?? "",
            displayName: response.employeeName,
            email: response.employeeEmail,
            phone: response.employeePhone,
            role: role,
            stations: [],
            isActive: true,
            createdAt: Date()
        )
    }

    private static func parseISO(_ string: String?) -> Date {
        guard let string else { return Date() }
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = formatter.date(from: string) { return date }
        formatter.formatOptions = [.withInternetDateTime]
        if let date = formatter.date(from: string) { return date }
        return Date()
    }
}
