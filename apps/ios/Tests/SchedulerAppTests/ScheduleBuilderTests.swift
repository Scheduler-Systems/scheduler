import XCTest
@testable import SchedulerApp

/// Characterization test: pins the Swift buildSchedule port to the canonical web
/// algorithm by reproducing scheduler-web/lib/schedule-builder.test.ts's golden cases
/// (the same set as the Android ScheduleBuilderTest), so web ↔ Android ↔ iOS agree.
final class ScheduleBuilderTests: XCTestCase {

    private let workers = ["Alice", "Bob", "Carol", "Dave"]

    func testEmptyGridWhenNoShifts() {
        let out = buildSchedule(BuildScheduleInput(employees: workers, enabledShifts: [], numDays: 7, numStations: 1))
        XCTAssertTrue(out.rows.isEmpty)
    }

    func testEmptyGridWhenNoDays() {
        let out = buildSchedule(BuildScheduleInput(employees: workers, enabledShifts: ["morning"], numDays: 0, numStations: 1))
        XCTAssertTrue(out.rows.isEmpty)
    }

    func testNumDaysTimesNumShiftsRows() {
        let out = buildSchedule(BuildScheduleInput(employees: workers, enabledShifts: ["morning", "night"], numDays: 3, numStations: 1))
        XCTAssertEqual(out.rows.count, 3 * 2)
        XCTAssertEqual(out.rows[0].count, 1)
        XCTAssertEqual(out.rows[1].count, 1)
    }

    func testAssignsNumStationsNamesPerSlot() {
        let out = buildSchedule(BuildScheduleInput(employees: workers, enabledShifts: ["morning"], numDays: 1, numStations: 3))
        XCTAssertEqual(out.rows.count, 1)
        XCTAssertEqual(out.rows[0].count, 3)
    }

    func testCyclesEmployeesRoundRobin() {
        let out = buildSchedule(BuildScheduleInput(employees: ["A", "B", "C"], enabledShifts: ["morning", "night"], numDays: 2, numStations: 1))
        XCTAssertEqual(out.rows.map { $0[0] }, ["A", "B", "C", "A"])
    }

    func testEmptyStringPlaceholdersWhenNoEmployees() {
        let out = buildSchedule(BuildScheduleInput(employees: [], enabledShifts: ["morning"], numDays: 1, numStations: 2))
        XCTAssertEqual(out.rows[0], ["", ""])
    }

    func testFlagsWorkerOnTwoShiftsSameDay() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Solo"], enabledShifts: ["morning", "night"], numDays: 1, numStations: 1))
        XCTAssertEqual(out.conflicts.count, 1)
        XCTAssertEqual(out.conflicts[0].worker, "Solo")
        XCTAssertEqual(out.conflicts[0].dayIndex, 0)
        XCTAssertEqual(out.conflicts[0].shifts, ["morning", "night"])
    }

    func testNoConflictsForWellDistributedBuild() {
        let out = buildSchedule(BuildScheduleInput(employees: workers, enabledShifts: ["morning", "night"], numDays: 3, numStations: 1))
        XCTAssertTrue(out.conflicts.isEmpty)
    }

    func testAvoidSameDayConflictsSkipsWorkerAlreadyOnDay() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Solo"], enabledShifts: ["morning", "night"], numDays: 1, numStations: 1, avoidSameDayConflicts: true))
        XCTAssertEqual(out.rows[0], ["Solo"])
        XCTAssertEqual(out.rows[1], [""])
        XCTAssertTrue(out.conflicts.isEmpty)
    }

    func testPrefersPriorityWorkerOverRoundRobin() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Alice", "Bob"], enabledShifts: ["morning"], numDays: 1, numStations: 1, startWeekday: 0, priorities: ["bob": ["Sun|morning"]]))
        XCTAssertEqual(out.rows[0][0], "Bob")
    }

    func testMatchesPrioritiesCaseInsensitively() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Alice", "Bob"], enabledShifts: ["morning"], numDays: 1, numStations: 1, startWeekday: 0, priorities: ["BOB": ["Sun|morning"]]))
        XCTAssertEqual(out.rows[0][0], "Bob")
    }

    func testAmongTiedPriorityPicksFewestAssignments() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Alice", "Bob", "Carol"], enabledShifts: ["morning"], numDays: 2, numStations: 1, startWeekday: 0, priorities: ["bob": ["Sun|morning", "Mon|morning"], "carol": ["Mon|morning"]]))
        XCTAssertEqual(out.rows[0][0], "Bob")
        XCTAssertEqual(out.rows[1][0], "Carol")
    }

    func testFallsBackToFairnessRoundRobin() {
        let out = buildSchedule(BuildScheduleInput(employees: ["A", "B", "C"], enabledShifts: ["morning"], numDays: 3, numStations: 1, priorities: [:]))
        XCTAssertEqual(out.rows.map { $0[0] }, ["A", "B", "C"])
    }

    func testRespectsAvoidSameDayConflictsForPriorityPicks() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Solo", "Other"], enabledShifts: ["morning", "night"], numDays: 1, numStations: 1, startWeekday: 0, avoidSameDayConflicts: true, priorities: ["solo": ["Sun|morning", "Sun|night"]]))
        XCTAssertEqual(out.rows[0][0], "Solo")
        XCTAssertEqual(out.rows[1][0], "Other")
    }

    func testPrioritiesIgnoredWhenWorkerNotOnRoster() {
        let out = buildSchedule(BuildScheduleInput(employees: ["A", "B"], enabledShifts: ["morning"], numDays: 1, numStations: 1, startWeekday: 0, priorities: ["ghost": ["Sun|morning"]]))
        XCTAssertEqual(out.rows[0][0], "A")
    }

    func testHandlesTrimmedWhitespaceInPriorityNames() {
        let out = buildSchedule(BuildScheduleInput(employees: ["Alice", "Bob"], enabledShifts: ["morning"], numDays: 1, numStations: 1, startWeekday: 0, priorities: ["  bob  ": ["Sun|morning"]]))
        XCTAssertEqual(out.rows[0][0], "Bob")
    }
}
