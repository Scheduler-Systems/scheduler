import XCTest
import Foundation
@testable import SchedulerApp

// MARK: - ApiError Tests

final class ApiErrorTests: XCTestCase {
    func testInvalidURLDescription() {
        XCTAssertEqual(ApiError.invalidURL.errorDescription, "Invalid API URL")
    }
    
    func testNotAuthenticatedDescription() {
        XCTAssertEqual(ApiError.notAuthenticated.errorDescription, "Not authenticated")
    }
    
    func testNetworkDescription() {
        let urlError = URLError(.notConnectedToInternet)
        let error = ApiError.network(urlError)
        XCTAssertEqual(error.errorDescription, urlError.localizedDescription)
    }
    
    func testServerDescription() {
        let error = ApiError.server(status: 500, message: "Internal Error")
        XCTAssertEqual(error.errorDescription, "[500] Internal Error")
    }
    
    func testDecodeDescription() {
        let error = ApiError.decode("type mismatch")
        XCTAssertEqual(error.errorDescription, "Decode error: type mismatch")
    }
    
    func testEncodeDescription() {
        let error = ApiError.encode("invalid type")
        XCTAssertEqual(error.errorDescription, "Encode error: invalid type")
    }
}

// MARK: - Mock URL Protocol

final class MockURLProtocol: URLProtocol {
    nonisolated(unsafe) static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?
    
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    
    override func startLoading() {
        guard let handler = MockURLProtocol.requestHandler else {
            client?.urlProtocol(self, didFailWithError: URLError(.unknown))
            return
        }
        
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }
    
    override func stopLoading() {}
}

// MARK: - ApiClient Tests

final class ApiClientTests: XCTestCase {
    var session: URLSession!
    var apiClient: ApiClient!
    let baseURL = URL(string: "https://api.test.com")!
    
    override func setUp() {
        super.setUp()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        session = URLSession(configuration: config)
        apiClient = ApiClient(baseURL: baseURL, session: session)
        
        // Firebase Auth mock — we need to stub Auth.auth().currentUser
        // Since we can't easily mock FirebaseAuth at the class level,
        // ApiClient.makeRequest calls Auth.auth().currentUser which requires Firebase.
        // For ApiClient coverage we test the model types and ApiError instead.
    }
    
    override func tearDown() {
        MockURLProtocol.requestHandler = nil
        session = nil
        apiClient = nil
        super.tearDown()
    }
    
    // MARK: - ApiError coverage
    
    func testApiErrorLocalizedDescription() {
        let errors: [ApiError] = [
            .invalidURL,
            .notAuthenticated,
            .network(URLError(.badURL)),
            .server(status: 404, message: "Not Found"),
            .decode("json parse"),
            .encode("body serialize")
        ]
        for error in errors {
            XCTAssertFalse(error.errorDescription?.isEmpty ?? true)
        }
    }
    
    // MARK: - ListResponse
    
    func testListResponseDecoding() throws {
        let json = """
        {"items": [{"id":"1","tenantId":"t1","name":"Test","status":"draft"}]}
        """
        let decoded = try JSONDecoder().decode(ListResponse<ScheduleResponse>.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.items.count, 1)
        XCTAssertEqual(decoded.items[0].id, "1")
    }
    
    // MARK: - AnyEncodable (tested indirectly)
    
    func testCreateScheduleRequestEncoding() throws {
        let req = CreateScheduleRequest(name: "Test", status: "published")
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(dict?["status"] as? String, "published")
    }
    
    // MARK: - ApiClient exists
    
    func testApiClientInitialized() {
        XCTAssertNotNil(apiClient)
    }
}

// MARK: - MockApiClient for ScheduleApiService Tests

final class MockApiClient: ApiClientProtocol {
    var fetchSchedulesResult: Result<[ScheduleResponse], Error> = .success([])
    var fetchScheduleResult: Result<ScheduleResponse, Error> = .success(
        ScheduleResponse(id: "1", tenantId: "t1", name: "Test", settings: nil, status: "draft", createdBy: nil, createdAt: nil, updatedAt: nil)
    )
    var fetchEmployeesResult: Result<[EmployeeResponse], Error> = .success([])
    var addEmployeeResult: Result<EmployeeResponse, Error> = .success(
        EmployeeResponse(employeeName: "Added", employeeEmail: "added@example.com", employeePhone: nil, role: nil, userRef: nil)
    )
    var fetchInvitationsResult: Result<[InvitationResponse], Error> = .success([])
    var createScheduleResult: Result<ScheduleResponse, Error> = .success(
        ScheduleResponse(id: "new", tenantId: "t1", name: "New", settings: nil, status: "draft", createdBy: nil, createdAt: nil, updatedAt: nil)
    )
    var updateScheduleResult: Result<ScheduleResponse, Error> = .success(
        ScheduleResponse(id: "1", tenantId: "t1", name: "Updated", settings: nil, status: "published", createdBy: nil, createdAt: nil, updatedAt: nil)
    )
    var deleteScheduleResult: Result<DeleteResponse, Error> = .success(DeleteResponse(success: true, id: "1"))
    var putAvailabilityResult: Result<AvailabilityResponse, Error> = .success(
        AvailabilityResponse(id: "a1", tenantId: "t1", scheduleId: "s1", userId: "u1", availability: nil, state: "open", createdAt: nil)
    )
    var createDraftResult: Result<DraftResponse, Error> = .success(
        DraftResponse(id: "d1", tenantId: "t1", scheduleId: "s1", shifts: nil, createdBy: "u1", createdAt: nil)
    )
    var publishScheduleResult: Result<PublishResponse, Error> = .success(
        PublishResponse(id: "p1", tenantId: "t1", scheduleId: "s1", draftId: "d1", publishedAt: nil)
    )
    var createRequestResult: Result<ScheduleRequestResponse, Error> = .success(
        ScheduleRequestResponse(id: "r1", tenantId: "t1", scheduleId: "s1", userId: "u1", type: "swap", details: nil, state: "pending", createdAt: nil)
    )
    
    var recordedTenantIds: [String] = []
    var recordedScheduleIds: [String] = []
    var recordedAvailability: [String: String]?
    
    func fetchSchedules(tenantId: String) async throws -> [ScheduleResponse] {
        recordedTenantIds.append(tenantId)
        return try fetchSchedulesResult.get()
    }
    
    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> ScheduleResponse {
        return try fetchScheduleResult.get()
    }

    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [EmployeeResponse] {
        recordedScheduleIds.append(scheduleId)
        return try fetchEmployeesResult.get()
    }

    func addEmployee(tenantId: String, scheduleId: String, body: AddEmployeeRequest) async throws -> EmployeeResponse {
        recordedScheduleIds.append(scheduleId)
        return try addEmployeeResult.get()
    }

    func fetchInvitations(tenantId: String, scheduleId: String) async throws -> [InvitationResponse] {
        recordedScheduleIds.append(scheduleId)
        return try fetchInvitationsResult.get()
    }

    func createSchedule(tenantId: String, body: CreateScheduleRequest) async throws -> ScheduleResponse {
        return try createScheduleResult.get()
    }
    
    func updateSchedule(tenantId: String, scheduleId: String, body: UpdateScheduleRequest) async throws -> ScheduleResponse {
        return try updateScheduleResult.get()
    }
    
    func deleteSchedule(tenantId: String, scheduleId: String) async throws -> DeleteResponse {
        recordedScheduleIds.append(scheduleId)
        return try deleteScheduleResult.get()
    }
    
    func putAvailability(tenantId: String, scheduleId: String, body: AvailabilityRequest) async throws -> AvailabilityResponse {
        recordedScheduleIds.append(scheduleId)
        recordedAvailability = body.availability
        return try putAvailabilityResult.get()
    }
    
    func createDraft(tenantId: String, scheduleId: String, body: DraftRequest) async throws -> DraftResponse {
        return try createDraftResult.get()
    }
    
    func publishSchedule(tenantId: String, scheduleId: String, body: PublishRequest) async throws -> PublishResponse {
        return try publishScheduleResult.get()
    }
    
    func createRequest(tenantId: String, scheduleId: String, body: ScheduleRequest) async throws -> ScheduleRequestResponse {
        return try createRequestResult.get()
    }
}

// MARK: - ScheduleApiService Tests

final class ScheduleApiServiceTests: XCTestCase {
    var mockApi: MockApiClient!
    var service: ScheduleApiService!
    
    override func setUp() {
        super.setUp()
        mockApi = MockApiClient()
        service = ScheduleApiService(api: mockApi)
    }
    
    override func tearDown() {
        mockApi = nil
        service = nil
        super.tearDown()
    }
    
    // MARK: - fetchSchedules
    
    func testFetchSchedulesSuccess() async throws {
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "Weekly", settings: nil, status: "published", createdBy: nil, createdAt: "2024-01-01T00:00:00Z", updatedAt: nil)
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        
        XCTAssertEqual(schedules.count, 1)
        XCTAssertEqual(schedules[0].id, "s1")
        XCTAssertEqual(schedules[0].name, "Weekly")
        XCTAssertEqual(schedules[0].status, .published)
        XCTAssertEqual(mockApi.recordedTenantIds, ["t1"])
    }
    
    func testFetchSchedulesEmpty() async throws {
        mockApi.fetchSchedulesResult = .success([])
        let schedules = try await service.fetchSchedules(tenantId: "t2")
        XCTAssertTrue(schedules.isEmpty)
    }
    
    func testFetchSchedulesError() async {
        struct ApiErr: Error {}
        mockApi.fetchSchedulesResult = .failure(ApiErr())
        
        do {
            _ = try await service.fetchSchedules(tenantId: "t1")
            XCTFail("Expected error")
        } catch {
            // expected
        }
    }
    
    func testFetchSchedulesMapping() async throws {
        let response = ScheduleResponse(
            id: "s-mapped", tenantId: "t-mapped", name: "Mapped Schedule",
            settings: nil, status: "archived", createdBy: "u1",
            createdAt: "2024-06-15T12:00:00.000Z", updatedAt: "2024-06-16T12:00:00.000Z"
        )
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        
        XCTAssertEqual(schedules.count, 1)
        XCTAssertEqual(schedules[0].status, .archived)
    }

    // MARK: - fetchEmployees

    func testFetchEmployeesMapsRosterRow() async throws {
        let response = EmployeeResponse(
            employeeName: "Alex Worker",
            employeeEmail: "alex.worker@example.com",
            employeePhone: "+15551234567",
            role: EmployeeRoleResponse(isCreator: false, isAdmin: false, isWorker: true),
            userRef: "uid-1"
        )
        mockApi.fetchEmployeesResult = .success([response])

        let employees = try await service.fetchEmployees(tenantId: "t1", scheduleId: "s1")

        XCTAssertEqual(employees.count, 1)
        let emp = employees[0]
        // email is the API's stable identity → used as the model id
        XCTAssertEqual(emp.id, "alex.worker@example.com")
        XCTAssertEqual(emp.email, "alex.worker@example.com")
        XCTAssertEqual(emp.displayName, "Alex Worker")
        XCTAssertEqual(emp.phone, "+15551234567")
        XCTAssertEqual(emp.userId, "uid-1")
        XCTAssertEqual(emp.role, .worker)
        XCTAssertTrue(mockApi.recordedScheduleIds.contains("s1"))
    }

    func testFetchEmployeesRoleMapping() async throws {
        let admin = EmployeeResponse(employeeName: "A", employeeEmail: "a@x.com", employeePhone: nil,
            role: EmployeeRoleResponse(isCreator: false, isAdmin: true, isWorker: false), userRef: nil)
        let creator = EmployeeResponse(employeeName: "C", employeeEmail: "c@x.com", employeePhone: nil,
            role: EmployeeRoleResponse(isCreator: true, isAdmin: false, isWorker: false), userRef: nil)
        mockApi.fetchEmployeesResult = .success([admin, creator])

        let employees = try await service.fetchEmployees(tenantId: "t1", scheduleId: "s1")

        XCTAssertEqual(employees[0].role, .admin)    // isAdmin wins
        XCTAssertEqual(employees[1].role, .manager)  // isCreator → manager
    }

    func testFetchEmployeesEmpty() async throws {
        mockApi.fetchEmployeesResult = .success([])
        let employees = try await service.fetchEmployees(tenantId: "t1", scheduleId: "s1")
        XCTAssertTrue(employees.isEmpty)
    }

    // MARK: - schedule settings

    func testFetchScheduleMapsNestedSettings() async throws {
        mockApi.fetchScheduleResult = .success(
            ScheduleResponse(
                id: "s1", tenantId: "t1", name: "S",
                settings: ScheduleSettingsPayload(
                    enabledShifts: EnabledShiftsPayload(morning: true, afternoon: false, night: true),
                    timezone: "UTC"),
                status: "active", createdBy: nil, createdAt: nil, updatedAt: nil)
        )
        let s = try await service.fetchSchedule(tenantId: "t1", scheduleId: "s1")
        // API morning/afternoon/night → domain mornings/afternoons/evenings
        XCTAssertTrue(s.settings.mornings)
        XCTAssertFalse(s.settings.afternoons)
        XCTAssertTrue(s.settings.evenings)
        XCTAssertEqual(s.settings.timezone, "UTC")
    }

    func testFetchScheduleDefaultsMissingSettings() async throws {
        mockApi.fetchScheduleResult = .success(
            ScheduleResponse(id: "s1", tenantId: "t1", name: "S", settings: nil,
                             status: "active", createdBy: nil, createdAt: nil, updatedAt: nil)
        )
        let s = try await service.fetchSchedule(tenantId: "t1", scheduleId: "s1")
        XCTAssertFalse(s.settings.mornings)
        XCTAssertFalse(s.settings.afternoons)
        XCTAssertFalse(s.settings.evenings)
    }

    // MARK: - addEmployee

    func testAddEmployeeMapsCreatedRow() async throws {
        mockApi.addEmployeeResult = .success(
            EmployeeResponse(employeeName: "New Hire", employeeEmail: "new.hire@example.com",
                             employeePhone: "+15559990000",
                             role: EmployeeRoleResponse(isCreator: false, isAdmin: false, isWorker: true),
                             userRef: nil)
        )
        let emp = try await service.addEmployee(tenantId: "t1", scheduleId: "s1",
                                                name: "New Hire", email: "new.hire@example.com", phone: "+15559990000")
        XCTAssertEqual(emp.id, "new.hire@example.com")   // email = identity
        XCTAssertEqual(emp.displayName, "New Hire")
        XCTAssertEqual(emp.role, .worker)
        XCTAssertTrue(mockApi.recordedScheduleIds.contains("s1"))
    }

    func testFetchInvitationsMapsAndLabelsStatus() async throws {
        mockApi.fetchInvitationsResult = .success([
            InvitationResponse(id: "i1", scheduleId: "s1", scheduleName: "QA Demo Schedule",
                               toUserIdentification: "invitee@example.com",
                               status: "ADD_RQUEST_PENDING", isAddRequest: true, createdAt: nil)
        ])
        let invites = try await service.fetchInvitations(tenantId: "t1", scheduleId: "s1")
        XCTAssertEqual(invites.count, 1)
        XCTAssertEqual(invites[0].invitee, "invitee@example.com")
        XCTAssertEqual(invites[0].scheduleName, "QA Demo Schedule")
        XCTAssertEqual(invites[0].statusLabel, "Pending")   // ADD_RQUEST_PENDING → Pending
    }

    func testAddEmployeeSurfacesError() async {
        struct AddErr: Error {}
        mockApi.addEmployeeResult = .failure(AddErr())
        do {
            _ = try await service.addEmployee(tenantId: "t1", scheduleId: "s1", name: "X", email: "x@x.com", phone: "")
            XCTFail("Expected error")
        } catch {
            // expected (e.g. 409 duplicate email surfaces to the caller)
        }
    }

    // MARK: - priorities submission (POST /availability)

    func testSubmitPriorities() async throws {
        try await service.submitAvailability(
            tenantId: "t1", scheduleId: "s1",
            availability: ["priorities": "Alex Worker,QA Verified", "selected": "Alex Worker"]
        )
        // The service posts to the schedule's availability endpoint with the selection.
        XCTAssertTrue(mockApi.recordedScheduleIds.contains("s1"))
        XCTAssertEqual(mockApi.recordedAvailability?["priorities"], "Alex Worker,QA Verified")
        XCTAssertEqual(mockApi.recordedAvailability?["selected"], "Alex Worker")
    }

    func testSubmitPrioritiesSurfacesError() async {
        struct SubmitErr: Error {}
        mockApi.putAvailabilityResult = .failure(SubmitErr())
        do {
            try await service.submitAvailability(tenantId: "t1", scheduleId: "s1", availability: [:])
            XCTFail("Expected error")
        } catch {
            // expected — a failed submit surfaces to the caller (screen shows the error)
        }
    }

    // The Go API serves current_priorities (snake_case); ScheduleResponse must decode it
    // and the service must map it onto Schedule.currentPriorities (drives the screen).
    func testFetchScheduleMapsCurrentPriorities() async throws {
        let json = """
        {"id":"s1","tenantId":"t1","name":"QA","settings":null,"status":"active",
         "current_priorities":["Alex Worker","QA Verified"]}
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(ScheduleResponse.self, from: json)
        XCTAssertEqual(decoded.currentPriorities, ["Alex Worker", "QA Verified"])

        mockApi.fetchScheduleResult = .success(decoded)
        let schedule = try await service.fetchSchedule(tenantId: "t1", scheduleId: "s1")
        XCTAssertEqual(schedule.currentPriorities, ["Alex Worker", "QA Verified"])
    }

    // MARK: - createSchedule
    
    func testCreateScheduleSuccess() async throws {
        let schedule = Schedule(
            id: "temp", tenantId: "t1", name: "New Schedule",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        
        let response = ScheduleResponse(id: "created-id", tenantId: "t1", name: "New Schedule", settings: nil, status: "draft", createdBy: nil, createdAt: nil, updatedAt: nil)
        mockApi.createScheduleResult = .success(response)
        
        let result = try await service.createSchedule(tenantId: "t1", schedule: schedule)
        XCTAssertEqual(result.id, "created-id")
        XCTAssertEqual(result.name, "New Schedule")
        XCTAssertEqual(result.status, .draft)
    }
    
    func testCreateScheduleError() async {
        let schedule = Schedule(
            id: "temp", tenantId: "t1", name: "Bad",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        
        struct CreateErr: Error {}
        mockApi.createScheduleResult = .failure(CreateErr())
        
        do {
            _ = try await service.createSchedule(tenantId: "t1", schedule: schedule)
            XCTFail("Expected error")
        } catch {
            // expected
        }
    }
    
    // MARK: - updateSchedule
    
    func testUpdateScheduleSuccess() async throws {
        let schedule = Schedule(
            id: "s1", tenantId: "t1", name: "Updated Name",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .published,
            createdAt: Date(), updatedAt: Date()
        )
        
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "Updated Name", settings: nil, status: "published", createdBy: nil, createdAt: nil, updatedAt: nil)
        mockApi.updateScheduleResult = .success(response)
        
        let result = try await service.updateSchedule(tenantId: "t1", schedule: schedule)
        XCTAssertEqual(result.id, "s1")
        XCTAssertEqual(result.status, .published)
    }
    
    func testUpdateScheduleError() async {
        let schedule = Schedule(
            id: "s1", tenantId: "t1", name: "Fail",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        
        struct UpdateErr: Error {}
        mockApi.updateScheduleResult = .failure(UpdateErr())
        
        do {
            _ = try await service.updateSchedule(tenantId: "t1", schedule: schedule)
            XCTFail("Expected error")
        } catch {
            // expected
        }
    }
    
    // MARK: - deleteSchedule
    
    func testDeleteScheduleSuccess() async throws {
        let response = DeleteResponse(success: true, id: "s1")
        mockApi.deleteScheduleResult = .success(response)
        
        try await service.deleteSchedule(tenantId: "t1", scheduleId: "s1")
        XCTAssertEqual(mockApi.recordedScheduleIds, ["s1"])
    }
    
    func testDeleteScheduleError() async {
        struct DeleteErr: Error {}
        mockApi.deleteScheduleResult = .failure(DeleteErr())
        
        do {
            try await service.deleteSchedule(tenantId: "t1", scheduleId: "s1")
            XCTFail("Expected error")
        } catch {
            // expected
        }
    }
    
    // MARK: - Status mapping edge cases
    
    func testScheduleStatusMappingInvalid() async throws {
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "BadStatus", settings: nil, status: "unknown_status", createdBy: nil, createdAt: nil, updatedAt: nil)
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        XCTAssertEqual(schedules[0].status, .draft)
    }
    
    func testDateParsingWithoutFractionalSeconds() async throws {
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "NoFrac", settings: nil, status: "draft", createdBy: nil, createdAt: "2024-01-01T00:00:00Z", updatedAt: "2024-01-02T00:00:00Z")
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        XCTAssertEqual(schedules.count, 1)
    }
    
    func testDateParsingInvalidFormat() async throws {
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "BadDate", settings: nil, status: "draft", createdBy: nil, createdAt: "not-a-date", updatedAt: "also-not-a-date")
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        XCTAssertEqual(schedules.count, 1)
    }
    
    func testDateParsingNilDates() async throws {
        let response = ScheduleResponse(id: "s1", tenantId: "t1", name: "NoDates", settings: nil, status: "draft", createdBy: nil, createdAt: nil, updatedAt: nil)
        mockApi.fetchSchedulesResult = .success([response])
        
        let schedules = try await service.fetchSchedules(tenantId: "t1")
        XCTAssertEqual(schedules.count, 1)
    }
}

// MARK: - MockScheduleApiService Tests (legacy mock used in existing tests)

final class MockScheduleApiServiceTests: XCTestCase {
    func testMockFetchSchedules() async throws {
        let mock = MockScheduleApiService()
        let schedules = try await mock.fetchSchedules(tenantId: "t1")
        XCTAssertTrue(schedules.isEmpty)
    }
    
    func testMockCreateSchedule() async throws {
        let mock = MockScheduleApiService()
        let schedule = Schedule(
            id: "s1", tenantId: "t1", name: "Test",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        let result = try await mock.createSchedule(tenantId: "t1", schedule: schedule)
        XCTAssertEqual(result.id, "s1")
    }
    
    func testMockUpdateSchedule() async throws {
        let mock = MockScheduleApiService()
        let schedule = Schedule(
            id: "s1", tenantId: "t1", name: "Test",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .published,
            createdAt: Date(), updatedAt: Date()
        )
        let result = try await mock.updateSchedule(tenantId: "t1", schedule: schedule)
        XCTAssertEqual(result.status, .published)
    }
    
    func testMockDeleteSchedule() async throws {
        let mock = MockScheduleApiService()
        try await mock.deleteSchedule(tenantId: "t1", scheduleId: "s1")
        // no throw = success
    }
}
