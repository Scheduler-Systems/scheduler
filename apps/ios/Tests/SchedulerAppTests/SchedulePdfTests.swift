import XCTest
@testable import SchedulerApp

/// Characterization tests for the pure schedule-PDF model. Mirrors the behaviors
/// pinned by the web's lib/pdf-export.test.ts and the Android SchedulePdfTest so the
/// native PDF stays faithful to the canonical reference across both platforms.
final class SchedulePdfTests: XCTestCase {

    // MARK: title

    func testTitleIncludesNameAndDateRange() {
        let t = schedulePdfTitle(scheduleName: "Summer Team", firstWeekday: "2026-05-03", lastWeekday: "2026-05-09")
        XCTAssertTrue(t.contains("Summer Team"))
        XCTAssertTrue(t.contains("Schedule"))
        XCTAssertTrue(t.contains("2026-05-03"))
        XCTAssertTrue(t.contains("2026-05-09"))
    }

    func testTitleDefaultsToUntitledWhenBlank() {
        let t = schedulePdfTitle(scheduleName: "")
        XCTAssertTrue(t.contains("Untitled"))
        XCTAssertTrue(t.contains("Schedule"))
    }

    func testTitleOmitsRangeWhenBothWeekdaysBlank() {
        XCTAssertEqual(schedulePdfTitle(scheduleName: "My Roster", firstWeekday: "", lastWeekday: ""), "My Roster Schedule")
    }

    func testTitleIncludesOnlyFirstWhenLastBlank() {
        XCTAssertTrue(schedulePdfTitle(scheduleName: "R", firstWeekday: "2026-05-03", lastWeekday: "").contains("2026-05-03"))
    }

    func testTitleIncludesOnlyLastWhenFirstBlank() {
        XCTAssertTrue(schedulePdfTitle(scheduleName: "R", firstWeekday: "", lastWeekday: "2026-05-09").contains("2026-05-09"))
    }

    // MARK: filename

    func testFilenameUsesScheduleName() {
        let name = schedulePdfFilename(scheduleName: "Q2 Roster")
        XCTAssertTrue(name.hasPrefix("Q2_Roster"))
        XCTAssertTrue(name.hasSuffix(".pdf"))
    }

    func testFilenameSanitizesUnsafeCharacters() {
        let name = schedulePdfFilename(scheduleName: "Team / Week: 21?")
        XCTAssertFalse(name.contains("/"))
        XCTAssertFalse(name.contains(":"))
        XCTAssertFalse(name.contains("?"))
        XCTAssertTrue(name.hasSuffix(".pdf"))
    }

    func testFilenameFallsBackWhenBlank() {
        XCTAssertTrue(schedulePdfFilename(scheduleName: "").lowercased().hasPrefix("schedule"))
    }

    func testFilenameTrimsWhitespace() {
        XCTAssertTrue(schedulePdfFilename(scheduleName: "  My Roster  ").hasPrefix("My_Roster"))
    }

    func testFilenameFallsBackWhenOnlySpecialChars() {
        XCTAssertTrue(schedulePdfFilename(scheduleName: "___").hasPrefix("schedule"))
    }

    // MARK: row expansion

    func testHeaderOrderIsShiftDayEmployee() {
        XCTAssertEqual(SchedulePdfDoc.header, ["Shift", "Day", "Employee"])
    }

    func testRowsExpandDayMajorOneRowPerWorker() {
        let grid: [[[String]]] = [
            [["Alice", "Bob"]], // day 0, shift 0
            [["Carol"]]         // day 1, shift 0
        ]
        let rows = buildSchedulePdfRows(enabledShifts: ["Morning"], grid: grid)
        XCTAssertEqual(rows.count, 3)
        XCTAssertEqual(rows[0].employee, "Alice")
        XCTAssertEqual(rows[1].employee, "Bob")
        XCTAssertEqual(rows[0].shift, "Morning")
        XCTAssertEqual(rows[0].day, rows[1].day) // same cell -> same day label
        XCTAssertEqual(rows[2].employee, "Carol")
    }

    func testRowsEmptyCellYieldsPlaceholderRow() {
        let grid: [[[String]]] = [[[], ["Bob"]]]
        let rows = buildSchedulePdfRows(enabledShifts: ["Morning", "Night"], grid: grid)
        XCTAssertEqual(rows.count, 2)
        XCTAssertEqual(rows[0].employee, "") // placeholder for empty morning cell
        XCTAssertEqual(rows[1].employee, "Bob")
    }

    func testRowsHandleNoEnabledShiftsGracefully() {
        let rows = buildSchedulePdfRows(enabledShifts: [], grid: [[["X"]]])
        XCTAssertFalse(rows.isEmpty)
        XCTAssertEqual(rows[0].employee, "X")
    }

    func testDocCombinesTitleFilenameRows() {
        let doc = buildSchedulePdfDoc(
            scheduleName: "QA Demo Schedule",
            enabledShifts: ["Morning"],
            grid: [[["Alex Worker"]]]
        )
        XCTAssertEqual(doc.title, "QA Demo Schedule Schedule")
        XCTAssertTrue(doc.filename.hasPrefix("QA_Demo_Schedule"))
        XCTAssertEqual(doc.rows[0].employee, "Alex Worker")
    }
}
