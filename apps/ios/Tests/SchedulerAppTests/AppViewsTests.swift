import XCTest
import SwiftUI
@testable import SchedulerApp

final class ScheduleDetailViewTests: XCTestCase {
    func testScheduleDetailViewInit() {
        let view = ScheduleDetailView(scheduleId: "test-id", scheduleService: MockScheduleApiService())
        XCTAssertNotNil(view)
    }
}

final class EmployeeListViewTests: XCTestCase {
    func testEmployeeListViewInit() {
        let view = EmployeeListView(scheduleId: "sched-1", scheduleService: MockScheduleApiService())
        XCTAssertNotNil(view)
    }
}

final class EmployeeDetailPlaceholderTests: XCTestCase {
    func testEmployeeDetailPlaceholderInit() {
        let view = EmployeeDetailPlaceholder(id: "emp-123")
        XCTAssertNotNil(view)
    }
}

final class FirestoreServiceProtocolTests: XCTestCase {
    func testFirestoreCollectionRawValues() {
        XCTAssertEqual(FirestoreCollection.schedules.rawValue, "schedules")
        XCTAssertEqual(FirestoreCollection.shifts.rawValue, "shifts")
        XCTAssertEqual(FirestoreCollection.employees.rawValue, "employees")
        XCTAssertEqual(FirestoreCollection.users.rawValue, "users")
        XCTAssertEqual(FirestoreCollection.tenants.rawValue, "tenants")
    }
}

final class ShellModeTests: XCTestCase {
    func testShellModeInit() {
        let mode = ShellMode(label: "test mode")
        XCTAssertEqual(mode.label, "test mode")
    }
}

final class ShiftStateTests: XCTestCase {
    func testShiftStateInit() {
        let shift = ShiftState(
            id: "s1", day: "Monday", startTime: "09:00",
            endTime: "17:00", assignedWorker: "Worker 1"
        )
        XCTAssertEqual(shift.id, "s1")
        XCTAssertEqual(shift.day, "Monday")
        XCTAssertEqual(shift.startTime, "09:00")
        XCTAssertEqual(shift.endTime, "17:00")
        XCTAssertEqual(shift.assignedWorker, "Worker 1")
    }
}

final class ScheduleStateTests: XCTestCase {
    func testScheduleStateInit() {
        let state = ScheduleState(
            id: "s1", tenantId: "t1", name: "Test",
            managerMode: ShellMode(label: "manage"),
            workerMode: ShellMode(label: "work"),
            shifts: []
        )
        XCTAssertEqual(state.id, "s1")
        XCTAssertEqual(state.name, "Test")
        XCTAssertTrue(state.shifts.isEmpty)
    }
}
