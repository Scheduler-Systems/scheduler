import XCTest
@testable import SchedulerApp

final class OnboardingContentTests: XCTestCase {
    func testPagesCount() {
        XCTAssertEqual(OnboardingContent.pages.count, 3)
    }

    func testPageIds() {
        let ids = OnboardingContent.pages.map(\.id)
        XCTAssertTrue(ids.contains("stay_connected"))
        XCTAssertTrue(ids.contains("customizable_approach"))
        XCTAssertTrue(ids.contains("algorithmic_calculation"))
    }
}

final class RouteTests: XCTestCase {
    func testRouteHashable() {
        let a = Route.home
        let b = Route.home
        XCTAssertEqual(a, b)
        XCTAssertEqual(a.hashValue, b.hashValue)
    }

    func testScheduleDetailRoute() {
        let route = Route.scheduleDetail("abc")
        if case .scheduleDetail(let id) = route {
            XCTAssertEqual(id, "abc")
        } else {
            XCTFail("Expected scheduleDetail")
        }
    }

    func testEmployeeDetailRoute() {
        let route = Route.employeeDetail("xyz")
        if case .employeeDetail(let id) = route {
            XCTAssertEqual(id, "xyz")
        } else {
            XCTFail("Expected employeeDetail")
        }
    }
}

final class RouterTests: XCTestCase {
    @MainActor
    func testPush() {
        let router = Router()
        XCTAssertEqual(router.path.count, 0)
        router.push(.home)
        XCTAssertEqual(router.path.count, 1)
    }

    @MainActor
    func testPop() {
        let router = Router()
        router.push(.login)
        router.push(.home)
        XCTAssertEqual(router.path.count, 2)
        router.pop()
        XCTAssertEqual(router.path.count, 1)
    }

    @MainActor
    func testPopToRoot() {
        let router = Router()
        router.push(.login)
        router.push(.home)
        router.push(.settings)
        router.popToRoot()
        XCTAssertEqual(router.path.count, 0)
    }

    @MainActor
    func testReplace() {
        let router = Router()
        router.push(.login)
        router.push(.home)
        router.replace(with: .onboarding)
        XCTAssertEqual(router.path.count, 1)
    }
}

final class ViewModelTests: XCTestCase {
    @MainActor
    func testOnboardingPages() {
        let vm = OnboardingViewModel()
        XCTAssertEqual(vm.pages.count, 3)
        XCTAssertEqual(vm.currentPage, 0)
    }

    @MainActor
    func testOnboardingNavigation() {
        let vm = OnboardingViewModel()
        vm.nextPage()
        XCTAssertEqual(vm.currentPage, 1)
        vm.nextPage()
        XCTAssertEqual(vm.currentPage, 2)
        vm.nextPage()
        XCTAssertEqual(vm.currentPage, 2)
        vm.previousPage()
        XCTAssertEqual(vm.currentPage, 1)
        vm.previousPage()
        XCTAssertEqual(vm.currentPage, 0)
        vm.previousPage()
        XCTAssertEqual(vm.currentPage, 0)
    }

    @MainActor
    func testOnboardingIsLastPage() {
        let vm = OnboardingViewModel()
        XCTAssertFalse(vm.isLastPage)
        vm.currentPage = 2
        XCTAssertTrue(vm.isLastPage)
    }

    @MainActor
    func testOnboardingComplete() {
        let vm = OnboardingViewModel()
        var completed = false
        vm.onComplete = { completed = true }
        vm.complete()
        XCTAssertTrue(vm.hasCompleted)
        XCTAssertTrue(completed)
    }

    @MainActor
    func testChooseRoleManager() {
        let vm = ChooseRoleViewModel()
        var role: UserRole?
        vm.onRoleSelected = { role = $0 }
        vm.selectManager()
        XCTAssertEqual(vm.selectedRole, .manager)
        XCTAssertEqual(role, .manager)
    }

    @MainActor
    func testChooseRoleEmployee() {
        let vm = ChooseRoleViewModel()
        vm.selectEmployee()
        XCTAssertEqual(vm.selectedRole, .employee)
    }

    @MainActor
    func testHomeViewModelInit() async {
        let mock = MockScheduleApiService()
        let vm = HomeViewModel(scheduleService: mock)
        XCTAssertFalse(vm.hasInitComplete)
        await vm.initialize()
        XCTAssertTrue(vm.hasInitComplete)
    }
}

final class MockScheduleApiService: ScheduleDataServiceProtocol {
    func fetchSchedules(tenantId: String) async throws -> [Schedule] { [] }
    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule {
        Schedule(id: scheduleId, tenantId: tenantId, name: "Mock", startDate: Date(), endDate: Date(), shifts: [], status: .draft, createdAt: Date(), updatedAt: Date())
    }
    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee] { [] }
    func fetchInvitations(tenantId: String, scheduleId: String) async throws -> [Invitation] { [] }
    func addEmployee(tenantId: String, scheduleId: String, name: String, email: String, phone: String) async throws -> Employee {
        Employee(id: email, tenantId: tenantId, userId: "", displayName: name, email: email, phone: phone, role: .worker, stations: [], isActive: true, createdAt: Date())
    }
    func createSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule { schedule }
    func updateSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule { schedule }
    func deleteSchedule(tenantId: String, scheduleId: String) async throws {}
    func submitAvailability(tenantId: String, scheduleId: String, availability: [String: String]) async throws {}
}

final class LegalDocumentsTests: XCTestCase {
    // Privacy Policy + Terms & Conditions both open the external Legal Center (parity
    // with Flutter's LegalDocumentsHelper). The policies screen drives this URL.
    func testLegalDocumentsURL() {
        XCTAssertEqual(LegalDocuments.legalCenterURLString, "https://scheduler-systems.com/legal")
        XCTAssertEqual(LegalDocuments.legalCenterURL.scheme, "https")
        XCTAssertEqual(LegalDocuments.legalCenterURL.host, "scheduler-systems.com")
    }
}

final class AuthModelTests: XCTestCase {
    func testAuthState() {
        XCTAssertFalse(AuthState.unauthenticated.isAuthenticated)
        XCTAssertTrue(AuthState.authenticating.isLoading)

        let user = AuthUser(
            id: "1", email: "test@test.com", displayName: "Test",
            photoURL: nil, phoneNumber: nil, isEmailVerified: true,
            providers: [.email]
        )
        let authenticated = AuthState.authenticated(user)
        XCTAssertTrue(authenticated.isAuthenticated)
        XCTAssertEqual(authenticated.user?.id, "1")
    }

    func testAuthStateError() {
        let errorState = AuthState.error("failed")
        XCTAssertFalse(errorState.isAuthenticated)
        XCTAssertNil(errorState.user)
        XCTAssertFalse(errorState.isLoading)
    }

    func testAuthUserDefaults() {
        let user = AuthUser(
            id: "", email: nil, displayName: nil,
            photoURL: nil, phoneNumber: nil, isEmailVerified: false,
            providers: []
        )
        XCTAssertFalse(user.isLoggedIn)
    }

    func testAuthProviderDisplayNames() {
        XCTAssertEqual(AuthProvider.email.displayName, "Email")
        XCTAssertEqual(AuthProvider.google.displayName, "Google")
        XCTAssertEqual(AuthProvider.apple.displayName, "Apple")
        XCTAssertEqual(AuthProvider.phone.displayName, "Phone")
        XCTAssertEqual(AuthProvider.anonymous.displayName, "Anonymous")
        XCTAssertEqual(AuthProvider.allCases.count, 5)
    }

    func testAuthErrorDescriptions() {
        XCTAssertEqual(AuthError.invalidEmail.errorDescription, "Invalid email address")
        XCTAssertEqual(AuthError.wrongPassword.errorDescription, "Incorrect password")
        XCTAssertEqual(AuthError.userNotFound.errorDescription, "No account found with this email")
        XCTAssertEqual(AuthError.emailAlreadyInUse.errorDescription, "Email is already registered")
        XCTAssertEqual(AuthError.weakPassword.errorDescription, "Password is too weak")
        XCTAssertEqual(AuthError.tooManyRequests.errorDescription, "Too many attempts. Please try again later")
        XCTAssertEqual(AuthError.networkError.errorDescription, "Network error. Please check your connection")
        XCTAssertEqual(AuthError.userCancelled.errorDescription, "Sign in was cancelled")
        XCTAssertEqual(AuthError.invalidCredential.errorDescription, "Invalid credentials")
        XCTAssertEqual(AuthError.invalidVerificationCode.errorDescription, "Invalid verification code")
        XCTAssertEqual(AuthError.appleSignInFailed.errorDescription, "Apple Sign In failed")
        XCTAssertEqual(AuthError.googleSignInFailed.errorDescription, "Google Sign In failed")
        XCTAssertEqual(AuthError.requiresRecentLogin.errorDescription, "Please sign in again to perform this action")
        XCTAssertEqual(AuthError.phoneAuthFailed("no signal").errorDescription, "no signal")
        XCTAssertEqual(AuthError.serverError("down").errorDescription, "down")
    }

    func testPhoneAuthState() {
        var state = PhoneAuthState()
        XCTAssertFalse(state.isCodeSent)
        XCTAssertNil(state.verificationID)
        state.verificationID = "vid"
        state.isCodeSent = true
        state.phoneNumber = "+123"
        XCTAssertTrue(state.isCodeSent)
        XCTAssertEqual(state.verificationID, "vid")
    }

    func testPasswordResetState() {
        XCTAssertEqual(PasswordResetState.idle, PasswordResetState.idle)
        XCTAssertNotEqual(PasswordResetState.sent, PasswordResetState.sending)
    }

    func testPasswordResetStateError() {
        let err = PasswordResetState.error("fail")
        XCTAssertNotEqual(err, PasswordResetState.idle)
        XCTAssertEqual(err, PasswordResetState.error("fail"))
        XCTAssertNotEqual(err, PasswordResetState.error("other"))
    }
}

final class UserModelTests: XCTestCase {
    func testUserAnonymous() {
        let user = User.anonymous
        XCTAssertEqual(user.id, "anonymous")
        XCTAssertNil(user.email)
        XCTAssertNil(user.displayName)
        XCTAssertNil(user.tenantId)
        XCTAssertNil(user.role)
        XCTAssertFalse(user.isPremium)
    }

    func testUserInitFull() {
        let date = Date()
        let user = User(
            id: "1", email: "a@b.com", displayName: "Alice",
            photoURL: "url", tenantId: "t1", role: .manager,
            isPremium: true, createdAt: date, lastLoginAt: date
        )
        XCTAssertEqual(user.id, "1")
        XCTAssertEqual(user.email, "a@b.com")
        XCTAssertEqual(user.role, .manager)
        XCTAssertTrue(user.isPremium)
    }

    func testUserRoleRawValues() {
        XCTAssertEqual(UserRole.employee.rawValue, "employee")
        XCTAssertEqual(UserRole.manager.rawValue, "manager")
        XCTAssertEqual(UserRole.admin.rawValue, "admin")
    }
}

final class TenantModelTests: XCTestCase {
    func testTenantPlans() {
        XCTAssertEqual(TenantPlan.free.rawValue, "free")
        XCTAssertEqual(TenantPlan.starter.rawValue, "starter")
        XCTAssertEqual(TenantPlan.professional.rawValue, "professional")
        XCTAssertEqual(TenantPlan.enterprise.rawValue, "enterprise")
    }

    func testTenantInit() {
        let date = Date(timeIntervalSince1970: 0)
        let tenant = Tenant(
            id: "t1", name: "Acme", ownerId: "o1",
            plan: .professional, maxEmployees: 50,
            features: ["a", "b"], createdAt: date
        )
        XCTAssertEqual(tenant.id, "t1")
        XCTAssertEqual(tenant.name, "Acme")
        XCTAssertEqual(tenant.plan, .professional)
        XCTAssertEqual(tenant.maxEmployees, 50)
        XCTAssertEqual(tenant.features, ["a", "b"])
    }
}

final class EmployeeModelTests: XCTestCase {
    func testEmployeeInit() {
        let date = Date(timeIntervalSince1970: 1)
        let emp = Employee(
            id: "e1", tenantId: "t1", userId: "u1",
            displayName: "Bob", email: "bob@test.com",
            phone: "555", role: .worker,
            stations: ["s1"], isActive: true, createdAt: date
        )
        XCTAssertEqual(emp.id, "e1")
        XCTAssertEqual(emp.displayName, "Bob")
        XCTAssertEqual(emp.role, .worker)
        XCTAssertTrue(emp.isActive)
        XCTAssertEqual(emp.stations, ["s1"])
    }

    func testEmployeeRoles() {
        XCTAssertEqual(EmployeeRole.worker.rawValue, "worker")
        XCTAssertEqual(EmployeeRole.manager.rawValue, "manager")
        XCTAssertEqual(EmployeeRole.admin.rawValue, "admin")
    }
}

final class ScheduleModelTests: XCTestCase {
    func testShiftInit() {
        let shift = Shift(
            id: "s1", scheduleId: "sch1", dayOfWeek: .monday,
            startTime: "09:00", endTime: "17:00",
            assignedWorkerId: "w1", stationId: "st1", notes: "note"
        )
        XCTAssertEqual(shift.id, "s1")
        XCTAssertEqual(shift.dayOfWeek, .monday)
        XCTAssertEqual(shift.assignedWorkerId, "w1")
        XCTAssertEqual(shift.notes, "note")
    }

    func testShiftNilDefaults() {
        let shift = Shift(
            id: "s2", scheduleId: "sch1", dayOfWeek: .friday,
            startTime: "08:00", endTime: "16:00",
            assignedWorkerId: nil, stationId: nil, notes: nil
        )
        XCTAssertNil(shift.assignedWorkerId)
        XCTAssertNil(shift.stationId)
        XCTAssertNil(shift.notes)
    }

    func testDayOfWeekAllCases() {
        XCTAssertEqual(DayOfWeek.allCases.count, 7)
        XCTAssertTrue(DayOfWeek.allCases.contains(.monday))
        XCTAssertTrue(DayOfWeek.allCases.contains(.sunday))
    }

    func testScheduleStatus() {
        XCTAssertEqual(ScheduleStatus.draft.rawValue, "draft")
        XCTAssertEqual(ScheduleStatus.published.rawValue, "published")
        XCTAssertEqual(ScheduleStatus.archived.rawValue, "archived")
    }

    func testScheduleInit() {
        let s = Date(timeIntervalSince1970: 0)
        let e = Date(timeIntervalSince1970: 86400)
        let schedule = Schedule(
            id: "sch1", tenantId: "t1", name: "Weekly",
            startDate: s, endDate: e, shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        XCTAssertEqual(schedule.id, "sch1")
        XCTAssertEqual(schedule.name, "Weekly")
        XCTAssertEqual(schedule.status, .draft)
    }
}

final class ApiModelTests: XCTestCase {
    func testShiftPayloadCodable() throws {
        let payload = ShiftPayload(
            dayOfWeek: "monday", startTime: "09:00", endTime: "17:00",
            assignedWorkerId: "w1"
        )
        let data = try JSONEncoder().encode(payload)
        let decoded = try JSONDecoder().decode(ShiftPayload.self, from: data)
        XCTAssertEqual(decoded.dayOfWeek, "monday")
        XCTAssertEqual(decoded.startTime, "09:00")
        XCTAssertEqual(decoded.assignedWorkerId, "w1")
    }

    func testScheduleResponseDecode() throws {
        let json = """
        {"id":"1","tenantId":"t1","name":"Test","status":"draft"}
        """
        let decoded = try JSONDecoder().decode(ScheduleResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, "1")
        XCTAssertEqual(decoded.name, "Test")
        XCTAssertEqual(decoded.status, "draft")
    }

    func testCreateScheduleRequestEncode() throws {
        let req = CreateScheduleRequest(name: "Test")
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(dict?["name"] as? String, "Test")
    }

    func testDeleteResponseDecode() throws {
        let json = """
        {"success":true,"id":"abc"}
        """
        let decoded = try JSONDecoder().decode(DeleteResponse.self, from: Data(json.utf8))
        XCTAssertTrue(decoded.success)
        XCTAssertEqual(decoded.id, "abc")
    }

    func testDraftResponseDecode() throws {
        let json = """
        {"id":"d1","tenantId":"t1","scheduleId":"s1","shifts":[],"createdBy":"u1"}
        """
        let decoded = try JSONDecoder().decode(DraftResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, "d1")
        XCTAssertEqual(decoded.createdBy, "u1")
    }

    func testPublishRequestEncode() throws {
        let req = PublishRequest(draftId: "d1")
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(dict?["draftId"] as? String, "d1")
    }

    func testPublishResponseDecode() throws {
        let json = """
        {"id":"p1","tenantId":"t1","scheduleId":"s1","draftId":"d1"}
        """
        let decoded = try JSONDecoder().decode(PublishResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, "p1")
        XCTAssertEqual(decoded.draftId, "d1")
    }

    func testAvailabilityResponseDecode() throws {
        let json = """
        {"id":"a1","tenantId":"t1","scheduleId":"s1","userId":"u1","state":"open"}
        """
        let decoded = try JSONDecoder().decode(AvailabilityResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, "a1")
        XCTAssertEqual(decoded.state, "open")
    }

    func testScheduleRequestResponseDecode() throws {
        let json = """
        {"id":"r1","tenantId":"t1","scheduleId":"s1","userId":"u1","type":"swap","state":"pending"}
        """
        let decoded = try JSONDecoder().decode(ScheduleRequestResponse.self, from: Data(json.utf8))
        XCTAssertEqual(decoded.id, "r1")
        XCTAssertEqual(decoded.type, "swap")
        XCTAssertEqual(decoded.state, "pending")
    }

    func testScheduleUpdatesEncode() throws {
        let updates = ScheduleUpdates(name: "new", settings: nil, status: "published")
        let req = UpdateScheduleRequest(updates: updates)
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let nested = dict?["updates"] as? [String: Any]
        XCTAssertEqual(nested?["name"] as? String, "new")
        XCTAssertEqual(nested?["status"] as? String, "published")
    }

    func testAvailabilityRequestEncode() throws {
        let req = AvailabilityRequest(availability: ["mon": "09:00-17:00"])
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let avail = dict?["availability"] as? [String: String]
        XCTAssertEqual(avail?["mon"], "09:00-17:00")
    }

    func testDraftRequestEncode() throws {
        let shifts = [ShiftPayload(dayOfWeek: "monday", startTime: "09:00", endTime: "17:00", assignedWorkerId: nil)]
        let req = DraftRequest(shifts: shifts)
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        let arr = dict?["shifts"] as? [[String: Any]]
        XCTAssertEqual(arr?.first?["dayOfWeek"] as? String, "monday")
    }

    func testScheduleRequestEncode() throws {
        let req = ScheduleRequest(type: "swap", details: ["reason": "conflict"])
        let data = try JSONEncoder().encode(req)
        let dict = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(dict?["type"] as? String, "swap")
    }
}

final class ScheduleStateModelTests: XCTestCase {
    func testMockSchedule() {
        let state = MockSchedule.state
        XCTAssertEqual(state.name, "Security Weekly Roster")
        XCTAssertEqual(state.shifts.count, 2)
        XCTAssertEqual(state.shifts[0].day, "Friday")
        XCTAssertEqual(state.shifts[1].assignedWorker, "Unassigned")
    }
}
