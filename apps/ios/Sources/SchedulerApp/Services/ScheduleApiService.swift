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
    func submitAvailability(tenantId: String, scheduleId: String, availability: [String: String]) async throws
    func updateDisplayName(tenantId: String, uid: String, email: String, name: String) async throws
    func updateRole(tenantId: String, uid: String, email: String, isManager: Bool) async throws
    func fetchNotifications(tenantId: String) async throws -> [NotificationResponse]
    /// Runs the canonical schedule builder for a schedule and persists the grid via the
    /// API. Returns the built grid (`[day][shift][station]`).
    func buildAndSaveSchedule(tenantId: String, scheduleId: String) async throws -> [[[String]]]
    /// The most recently built grid, or nil if none has been built.
    func latestBuiltSchedule(tenantId: String, scheduleId: String) async throws -> [[[String]]]?
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

    // Priorities/availability submission → POST /availability (202). Not retried (side effect).
    func submitAvailability(tenantId: String, scheduleId: String, availability: [String: String]) async throws {
        _ = try await api.putAvailability(
            tenantId: tenantId, scheduleId: scheduleId,
            body: AvailabilityRequest(availability: availability)
        )
    }

    // Auth onboarding: get-name persists display_name (PUT /users/{uid}); choose-role
    // persists the role (PUT /users/{uid}/role). Server computes the role string from the
    // RoleStruct. Not retried (side effects).
    func updateDisplayName(tenantId: String, uid: String, email: String, name: String) async throws {
        _ = try await api.upsertProfile(
            tenantId: tenantId, uid: uid,
            body: UpsertProfileRequest(email: email, displayName: name)
        )
    }

    func updateRole(tenantId: String, uid: String, email: String, isManager: Bool) async throws {
        // Manager → creator+admin; employee → worker (parity with roleStructToFlutterString).
        let role = RoleStructPayload(isCreator: isManager, isAdmin: isManager, isWorker: !isManager)
        _ = try await api.upsertRole(
            tenantId: tenantId, uid: uid,
            body: UpsertRoleRequest(email: email, role: role)
        )
    }

    // Notification feed — idempotent GET, retried (parity with the other read paths).
    func fetchNotifications(tenantId: String) async throws -> [NotificationResponse] {
        try await Self.withRetry { try await self.api.fetchNotifications(tenantId: tenantId) }
    }

    func buildAndSaveSchedule(tenantId: String, scheduleId: String) async throws -> [[[String]]] {
        let schedule = try await fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
        let employees = try await fetchEmployees(tenantId: tenantId, scheduleId: scheduleId)
        let s = schedule.settings
        var enabledShifts: [String] = []
        if s.mornings { enabledShifts.append("Morning") }
        if s.afternoons { enabledShifts.append("Afternoon") }
        if s.evenings { enabledShifts.append("Night") }
        if enabledShifts.isEmpty { enabledShifts = ["Morning", "Afternoon", "Night"] }
        let numDays = 7
        let numStations = 1

        let out = buildSchedule(BuildScheduleInput(
            employees: employees.map { $0.displayName },
            enabledShifts: enabledShifts,
            numDays: numDays,
            numStations: numStations
        ))
        let numShifts = enabledShifts.count
        let grid: [[[String]]] = (0..<numDays).map { d in
            (0..<numShifts).map { sh in out.rows[d * numShifts + sh] }
        }
        let resp = try await api.saveBuiltSchedule(
            tenantId: tenantId, scheduleId: scheduleId,
            body: SaveBuiltScheduleRequest(
                schedule: grid, firstWeekday: "", lastWeekday: "",
                currentPriorities: schedule.currentPriorities
            )
        )
        return resp.schedule ?? grid
    }

    func latestBuiltSchedule(tenantId: String, scheduleId: String) async throws -> [[[String]]]? {
        do {
            return try await api.latestBuiltSchedule(tenantId: tenantId, scheduleId: scheduleId).schedule
        } catch {
            // 404 = none built yet.
            return nil
        }
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
            settings: settings,
            currentPriorities: response.currentPriorities ?? []
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
