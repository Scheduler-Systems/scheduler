import Foundation

protocol ScheduleDataServiceProtocol {
    func fetchSchedules(tenantId: String) async throws -> [Schedule]
    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule
    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee]
    func fetchInvitations(tenantId: String, scheduleId: String) async throws -> [Invitation]
    func addEmployee(tenantId: String, scheduleId: String, name: String, email: String, phone: String) async throws -> Employee
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
        let items = try await Self.withRetry { try await self.api.fetchSchedules(tenantId: tenantId) }
        return items.map { Self.map($0) }
    }

    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule {
        let result = try await Self.withRetry { try await self.api.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId) }
        return Self.map(result)
    }

    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee] {
        let items = try await Self.withRetry { try await self.api.fetchEmployees(tenantId: tenantId, scheduleId: scheduleId) }
        return items.map { Self.map($0, tenantId: tenantId) }
    }

    func fetchInvitations(tenantId: String, scheduleId: String) async throws -> [Invitation] {
        let items = try await Self.withRetry { try await self.api.fetchInvitations(tenantId: tenantId, scheduleId: scheduleId) }
        return items.map {
            Invitation(
                id: $0.id,
                scheduleName: $0.scheduleName ?? "",
                invitee: $0.toUserIdentification ?? "",
                status: $0.status ?? ""
            )
        }
    }

    func addEmployee(tenantId: String, scheduleId: String, name: String, email: String, phone: String) async throws -> Employee {
        // POST is not retried (side effect; the server 409s on duplicate email).
        let body = AddEmployeeRequest(name: name, email: email, phone: phone)
        let result = try await api.addEmployee(tenantId: tenantId, scheduleId: scheduleId, body: body)
        return Self.map(result, tenantId: tenantId)
    }

    // Bounded retry for idempotent GETs only. On a cold app start (or host under
    // load) the first request can fail/time out; a one-shot fetch would leave the
    // view silently empty (Android's repository polls and self-heals — this gives
    // iOS the same resilience). NOT used for create/update/delete (side effects).
    private static func withRetry<T>(_ attempts: Int = 3, _ op: () async throws -> T) async throws -> T {
        var lastError: Error?
        for attempt in 1...attempts {
            do {
                return try await op()
            } catch {
                lastError = error
                if attempt < attempts {
                    try? await Task.sleep(nanoseconds: 700_000_000)
                }
            }
        }
        throw lastError ?? ApiError.server(status: 0, message: "retry exhausted")
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
            settings: ScheduleSettingsPayload(
                enabledShifts: EnabledShiftsPayload(
                    morning: schedule.settings.mornings,
                    afternoon: schedule.settings.afternoons,
                    night: schedule.settings.evenings
                ),
                timezone: schedule.settings.timezone
            ),
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
        let shifts = response.settings?.enabledShifts
        let settings = ScheduleSettings(
            mornings: shifts?.morning ?? false,
            afternoons: shifts?.afternoon ?? false,
            evenings: shifts?.night ?? false,
            timezone: response.settings?.timezone ?? "UTC"
        )
        return Schedule(
            id: response.id,
            tenantId: response.tenantId,
            name: response.name,
            startDate: Date(),
            endDate: Date().addingTimeInterval(604800),
            shifts: [],
            status: status,
            createdAt: parseISO(response.createdAt),
            updatedAt: parseISO(response.updatedAt),
            settings: settings
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
