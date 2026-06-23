import XCTest
@testable import SchedulerApp

/// Mirrors the Android ScheduleIcsTest so the .ics export is faithful across platforms.
final class ScheduleIcsTests: XCTestCase {

    // 2026-06-22 is a Monday; epoch-day = days since 1970-01-01.
    private let mondayEpoch = 20626  // 2026-06-22

    func testProducesValidVCalendarEnvelope() {
        let ics = buildScheduleIcs(scheduleName: "QA Demo Schedule", enabledShifts: ["Morning"], grid: [[["Alex Worker"]]], weekStartEpochDay: mondayEpoch)
        XCTAssertTrue(ics.hasPrefix("BEGIN:VCALENDAR"))
        XCTAssertTrue(ics.contains("VERSION:2.0"))
        XCTAssertTrue(ics.trimmingCharacters(in: .whitespacesAndNewlines).hasSuffix("END:VCALENDAR"))
        XCTAssertTrue(ics.contains("X-WR-CALNAME:QA Demo Schedule"))
    }

    func testOneVeventPerAssignedWorkerWithRealName() {
        let grid: [[[String]]] = [[["Alex Worker", "Sam"]], [["Carol"]]]
        let ics = buildScheduleIcs(scheduleName: "Roster", enabledShifts: ["Morning"], grid: grid, weekStartEpochDay: mondayEpoch)
        XCTAssertEqual(ics.components(separatedBy: "BEGIN:VEVENT").count - 1, 3)
        XCTAssertTrue(ics.contains("SUMMARY:Morning shift — Alex Worker"))
        XCTAssertTrue(ics.contains("SUMMARY:Morning shift — Sam"))
        XCTAssertTrue(ics.contains("SUMMARY:Morning shift — Carol"))
    }

    func testAnchorsDatesToTheWeekStart() {
        let grid: [[[String]]] = [[["A"]], [["B"]]]
        let ics = buildScheduleIcs(scheduleName: "R", enabledShifts: ["Morning"], grid: grid, weekStartEpochDay: mondayEpoch)
        XCTAssertTrue(ics.contains("DTSTART;VALUE=DATE:20260622"))
        XCTAssertTrue(ics.contains("DTSTART;VALUE=DATE:20260623"))
    }

    func testEmptyCellsProduceNoEvents() {
        let grid: [[[String]]] = [[[], ["Bob"]]]
        let ics = buildScheduleIcs(scheduleName: "R", enabledShifts: ["Morning", "Night"], grid: grid, weekStartEpochDay: mondayEpoch)
        XCTAssertEqual(ics.components(separatedBy: "BEGIN:VEVENT").count - 1, 1)
        XCTAssertTrue(ics.contains("Night shift — Bob"))
    }

    func testFilenameSanitized() {
        XCTAssertTrue(scheduleIcsFilename(scheduleName: "QA Demo Schedule").hasPrefix("QA_Demo_Schedule"))
        XCTAssertTrue(scheduleIcsFilename(scheduleName: "a/b:c?").hasSuffix(".ics"))
        XCTAssertTrue(scheduleIcsFilename(scheduleName: "").hasPrefix("schedule"))
    }
}
