import Foundation

/// Pure, framework-free model of the printable schedule PDF. The row-expansion,
/// title, and filename rules are a faithful port of the web's lib/pdf-export.ts
/// (the production-canonical reference) and match the Android SchedulePdf.kt — kept
/// off UIKit so it stays unit-testable; SchedulePdfRenderer turns it into real bytes.
///
/// Native built schedules carry only the assignment grid (employee names per
/// day/shift) — the Go API persists no per-shift hours or per-cell priorities — so
/// the table is Shift · Day · Employee, the real data we actually have. (The web adds
/// Start/End/Priority columns from settings the native model does not store;
/// fabricating blank columns here would be speculative, so they are omitted.)

private let dayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

struct SchedulePdfRow: Equatable {
    let shift: String
    let day: String
    let employee: String
}

struct SchedulePdfDoc: Equatable {
    let title: String
    let filename: String
    let rows: [SchedulePdfRow]

    /// Contractually-fixed header order (see SchedulePdfTests).
    static let header = ["Shift", "Day", "Employee"]
}

/// Deterministic ordinal -> label for days (e.g. "Sun #1").
private func formatDay(_ dayIndex: Int) -> String { "\(dayLabels[dayIndex % 7]) #\(dayIndex + 1)" }

/// "{name} Schedule · {first} — {last}"; range omitted when both weekdays blank.
func schedulePdfTitle(scheduleName: String, firstWeekday: String = "", lastWeekday: String = "") -> String {
    let trimmed = scheduleName.trimmingCharacters(in: .whitespaces)
    let name = trimmed.isEmpty ? "Untitled" : trimmed
    let first = firstWeekday.trimmingCharacters(in: .whitespaces)
    let last = lastWeekday.trimmingCharacters(in: .whitespaces)
    let range: String
    if !first.isEmpty && !last.isEmpty {
        range = "\(first) — \(last)"
    } else {
        range = first.isEmpty ? last : first
    }
    return range.isEmpty ? "\(name) Schedule" : "\(name) Schedule · \(range)"
}

/// Sanitizes unsafe filesystem characters; falls back to "schedule".
func schedulePdfFilename(scheduleName: String) -> String {
    let trimmed = scheduleName.trimmingCharacters(in: .whitespaces)
    let base = trimmed.isEmpty ? "schedule" : trimmed
    let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    // Replace any run of disallowed chars with a single underscore.
    var result = ""
    var lastWasUnderscore = false
    for scalar in base.unicodeScalars {
        if allowed.contains(scalar) {
            result.unicodeScalars.append(scalar)
            lastWasUnderscore = false
        } else if !lastWasUnderscore {
            result.append("_")
            lastWasUnderscore = true
        }
    }
    let safe = result.trimmingCharacters(in: CharacterSet(charactersIn: "_"))
    return "\(safe.isEmpty ? "schedule" : safe).pdf"
}

/// Expands the day-major grid (grid[day][shift] = the station name(s) for that
/// slot) into one table row per assigned worker; an unassigned slot yields a single
/// placeholder row with a blank employee — mirrors the web's roster shape.
func buildSchedulePdfRows(enabledShifts: [String], grid: [[[String]]]) -> [SchedulePdfRow] {
    let shifts = enabledShifts.isEmpty ? [""] : enabledShifts
    var out: [SchedulePdfRow] = []
    for (d, dayShifts) in grid.enumerated() {
        for s in shifts.indices {
            let names = (s < dayShifts.count ? dayShifts[s] : []).filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            let shift = shifts[s]
            let day = formatDay(d)
            if names.isEmpty {
                out.append(SchedulePdfRow(shift: shift, day: day, employee: ""))
            } else {
                for name in names { out.append(SchedulePdfRow(shift: shift, day: day, employee: name)) }
            }
        }
    }
    return out
}

func buildSchedulePdfDoc(
    scheduleName: String,
    enabledShifts: [String],
    grid: [[[String]]],
    firstWeekday: String = "",
    lastWeekday: String = ""
) -> SchedulePdfDoc {
    SchedulePdfDoc(
        title: schedulePdfTitle(scheduleName: scheduleName, firstWeekday: firstWeekday, lastWeekday: lastWeekday),
        filename: schedulePdfFilename(scheduleName: scheduleName),
        rows: buildSchedulePdfRows(enabledShifts: enabledShifts, grid: grid)
    )
}
