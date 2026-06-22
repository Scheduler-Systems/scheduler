import XCTest
@testable import SchedulerApp

final class MockScheduleDataService: ScheduleDataServiceProtocol {
    var fetchSchedulesResult: Result<[Schedule], Error> = .success([])
    var createScheduleResult: Result<Schedule, Error> = .success(
        Schedule(id: "s1", tenantId: "t1", name: "Test", startDate: Date(), endDate: Date(), shifts: [], status: .draft, createdAt: Date(), updatedAt: Date())
    )
    var updateScheduleResult: Result<Schedule, Error> = .success(
        Schedule(id: "s1", tenantId: "t1", name: "Updated", startDate: Date(), endDate: Date(), shifts: [], status: .published, createdAt: Date(), updatedAt: Date())
    )
    var deleteScheduleError: Error?
    var fetchEmployeesResult: Result<[Employee], Error> = .success([])

    var fetchedTenantIds: [String] = []
    var fetchedEmployeeScheduleIds: [String] = []
    var createdSchedules: [Schedule] = []
    var updatedSchedules: [Schedule] = []
    var deletedScheduleIds: [String] = []
    
    func fetchSchedules(tenantId: String) async throws -> [Schedule] {
        fetchedTenantIds.append(tenantId)
        return try fetchSchedulesResult.get()
    }

    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> Schedule {
        Schedule(id: scheduleId, tenantId: tenantId, name: "Test", startDate: Date(), endDate: Date(), shifts: [], status: .draft, createdAt: Date(), updatedAt: Date())
    }

    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [Employee] {
        fetchedEmployeeScheduleIds.append(scheduleId)
        return try fetchEmployeesResult.get()
    }

    func addEmployee(tenantId: String, scheduleId: String, name: String, email: String, phone: String) async throws -> Employee {
        Employee(id: email, tenantId: tenantId, userId: "", displayName: name, email: email, phone: phone, role: .worker, stations: [], isActive: true, createdAt: Date())
    }

    func fetchInvitations(tenantId: String, scheduleId: String) async throws -> [Invitation] { [] }

    func createSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule {
        createdSchedules.append(schedule)
        return try createScheduleResult.get()
    }
    
    func updateSchedule(tenantId: String, schedule: Schedule) async throws -> Schedule {
        updatedSchedules.append(schedule)
        return try updateScheduleResult.get()
    }
    
    func deleteSchedule(tenantId: String, scheduleId: String) async throws {
        if let error = deleteScheduleError { throw error }
        deletedScheduleIds.append(scheduleId)
    }

    func submitAvailability(tenantId: String, scheduleId: String, availability: [String: String]) async throws {}
}

// MARK: - BaseViewModel Tests

final class BaseViewModelTests: XCTestCase {
    @MainActor
    func testHandleError() {
        let vm = BaseViewModel()
        struct TestErr: LocalizedError { var errorDescription: String? { "test" } }
        let error = TestErr()
        vm.handle(error)
        XCTAssertNotNil(vm.error)
    }
    
    @MainActor
    func testClearError() {
        let vm = BaseViewModel()
        struct TestErr: LocalizedError { var errorDescription: String? { "test" } }
        vm.handle(TestErr())
        vm.clearError()
        XCTAssertNil(vm.error)
    }
    
    @MainActor
    func testInitialIsLoading() {
        let vm = BaseViewModel()
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testCancellablesInitialized() {
        let vm = BaseViewModel()
        XCTAssertNotNil(vm.cancellables)
    }
}

// MARK: - ScheduleViewModel Tests

final class ScheduleViewModelTests: XCTestCase {
    var mockService: MockScheduleDataService!
    
    @MainActor
    override func setUp() {
        super.setUp()
        mockService = MockScheduleDataService()
    }
    
    override func tearDown() {
        mockService = nil
        super.tearDown()
    }
    
    @MainActor
    func testInitialState() {
        let vm = ScheduleViewModel(scheduleService: mockService)
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertNil(vm.selectedSchedule)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesSuccess() async {
        let date = Date()
        let expectedSchedule = Schedule(
            id: "sch1", tenantId: "t1", name: "Weekly Roster",
            startDate: date, endDate: date.addingTimeInterval(604800),
            shifts: [], status: .draft, createdAt: date, updatedAt: date
        )
        mockService.fetchSchedulesResult = .success([expectedSchedule])
        
        let vm = ScheduleViewModel(scheduleService: mockService)
        await vm.loadSchedules(tenantId: "t1")
        
        XCTAssertEqual(vm.schedules.count, 1)
        XCTAssertEqual(vm.schedules.first?.id, "sch1")
        XCTAssertEqual(vm.schedules.first?.name, "Weekly Roster")
        XCTAssertEqual(mockService.fetchedTenantIds, ["t1"])
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesEmpty() async {
        mockService.fetchSchedulesResult = .success([])
        let vm = ScheduleViewModel(scheduleService: mockService)
        await vm.loadSchedules(tenantId: "t2")
        
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesError() async {
        struct FetchError: Error {}
        mockService.fetchSchedulesResult = .failure(FetchError())
        let vm = ScheduleViewModel(scheduleService: mockService)
        await vm.loadSchedules(tenantId: "t1")
        
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertNotNil(vm.error)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testSelectSchedule() {
        let vm = ScheduleViewModel(scheduleService: mockService)
        let schedule = Schedule(
            id: "s1", tenantId: "t1", name: "Test",
            startDate: Date(), endDate: Date(),
            shifts: [], status: .draft,
            createdAt: Date(), updatedAt: Date()
        )
        vm.selectSchedule(schedule)
        XCTAssertEqual(vm.selectedSchedule?.id, "s1")
    }
}

// MARK: - HomeViewModel Tests

final class HomeViewModelTests: XCTestCase {
    var mockService: MockScheduleDataService!
    
    override func setUp() {
        super.setUp()
        mockService = MockScheduleDataService()
    }
    
    override func tearDown() {
        mockService = nil
        super.tearDown()
    }
    
    @MainActor
    func testInitialState() {
        let vm = HomeViewModel(scheduleService: mockService)
        XCTAssertFalse(vm.hasInitComplete)
        XCTAssertFalse(vm.isLoading)
        XCTAssertEqual(vm.schedulesInvolvedCount, 0)
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertNil(vm.displayName)
    }
    
    @MainActor
    func testInitializeWithoutAuth() async {
        let vm = HomeViewModel(scheduleService: mockService)
        await vm.initialize()
        
        XCTAssertTrue(vm.hasInitComplete)
        XCTAssertNil(vm.displayName)
        XCTAssertTrue(vm.schedules.isEmpty)
    }
    
    @MainActor
    func testInitializeWithAuthAndSchedules() async {
        let mockAuth = MockAuthService()
        let user = AuthUser(
            id: "tenant-1", email: "manager@test.com", displayName: "Manager",
            photoURL: nil, phoneNumber: nil, isEmailVerified: true,
            providers: [.email]
        )
        mockAuth.authStateSubject.send(.authenticated(user))
        let authVM = AuthViewModel(authService: mockAuth)
        await Task.yield()
        
        let date = Date()
        let schedules = [
            Schedule(id: "s1", tenantId: "t1", name: "Weekly", startDate: date, endDate: date, shifts: [], status: .draft, createdAt: date, updatedAt: date),
            Schedule(id: "s2", tenantId: "t1", name: "Daily", startDate: date, endDate: date, shifts: [], status: .published, createdAt: date, updatedAt: date)
        ]
        mockService.fetchSchedulesResult = .success(schedules)
        
        let vm = HomeViewModel(scheduleService: mockService, authViewModel: authVM)
        await vm.initialize()
        
        XCTAssertTrue(vm.hasInitComplete)
        XCTAssertEqual(vm.displayName, "Manager")
        XCTAssertEqual(vm.schedules.count, 2)
        XCTAssertEqual(vm.schedulesInvolvedCount, 2)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesNoTenantId() async {
        let vm = HomeViewModel(scheduleService: mockService)
        await vm.loadSchedules()
        
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertTrue(mockService.fetchedTenantIds.isEmpty)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesError() async {
        let mockAuth = MockAuthService()
        let user = AuthUser(
            id: "tenant-1", email: "test@test.com", displayName: nil,
            photoURL: nil, phoneNumber: nil, isEmailVerified: true,
            providers: [.email]
        )
        mockAuth.authStateSubject.send(.authenticated(user))
        let authVM = AuthViewModel(authService: mockAuth)
        await Task.yield()
        
        struct FetchError: Error {}
        mockService.fetchSchedulesResult = .failure(FetchError())
        
        let vm = HomeViewModel(scheduleService: mockService, authViewModel: authVM)
        await vm.loadSchedules()
        
        XCTAssertTrue(vm.schedules.isEmpty)
        XCTAssertNotNil(vm.error)
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testLoadSchedulesSuccess() async {
        let mockAuth = MockAuthService()
        let user = AuthUser(
            id: "tenant-2", email: "user@test.com", displayName: "User",
            photoURL: nil, phoneNumber: nil, isEmailVerified: true,
            providers: [.email]
        )
        mockAuth.authStateSubject.send(.authenticated(user))
        let authVM = AuthViewModel(authService: mockAuth)
        await Task.yield()
        
        let date = Date()
        let schedules = [
            Schedule(id: "s1", tenantId: "t2", name: "Weekend", startDate: date, endDate: date, shifts: [], status: .archived, createdAt: date, updatedAt: date)
        ]
        mockService.fetchSchedulesResult = .success(schedules)
        
        let vm = HomeViewModel(scheduleService: mockService, authViewModel: authVM)
        await vm.loadSchedules()
        
        XCTAssertEqual(vm.schedules.count, 1)
        XCTAssertEqual(vm.schedulesInvolvedCount, 1)
        XCTAssertEqual(mockService.fetchedTenantIds, ["tenant-2"])
        XCTAssertFalse(vm.isLoading)
    }
    
    @MainActor
    func testHomeViewModelInheritsBase() {
        let vm = HomeViewModel(scheduleService: mockService)
        vm.clearError()
        XCTAssertNil(vm.error)
    }
}

// MARK: - OnboardingViewModel Tests (completing missing coverage)

final class OnboardingViewModelFullTests: XCTestCase {
    @MainActor
    func testGoToPage() {
        let vm = OnboardingViewModel()
        vm.goToPage(0)
        XCTAssertEqual(vm.currentPage, 0)
        vm.goToPage(2)
        XCTAssertEqual(vm.currentPage, 2)
    }
    
    @MainActor
    func testGoToPageOutOfBounds() {
        let vm = OnboardingViewModel()
        vm.goToPage(-1)
        XCTAssertEqual(vm.currentPage, 0)
        vm.goToPage(10)
        XCTAssertEqual(vm.currentPage, 0)
    }
    
    @MainActor
    func testPreviousPageAtStart() {
        let vm = OnboardingViewModel()
        vm.previousPage()
        XCTAssertEqual(vm.currentPage, 0)
    }
}
