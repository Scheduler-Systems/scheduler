import Foundation

/// Pure, framework-free generator of an iCalendar (.ics, RFC 5545) export of the built
/// schedule — mirrors the Android ScheduleIcs.kt. One all-day VEVENT per assigned
/// (day, shift, employee), anchored to a week starting at `weekStartEpochDay`. All-day
/// (VALUE=DATE) events avoid fabricating shift hours the native built-schedule doesn't carry.
/// Imports into Google Calendar and every other calendar app — a credential-free real export.

private let icsDayLabels = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

private func icsEscape(_ s: String) -> String {
    s.replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: ";", with: "\\;")
        .replacingOccurrences(of: ",", with: "\\,")
        .replacingOccurrences(of: "\n", with: "\\n")
}

func scheduleIcsFilename(scheduleName: String) -> String {
    let trimmed = scheduleName.trimmingCharacters(in: .whitespaces)
    let base = trimmed.isEmpty ? "schedule" : trimmed
    let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
    var result = ""
    var lastUnderscore = false
    for scalar in base.unicodeScalars {
        if allowed.contains(scalar) { result.unicodeScalars.append(scalar); lastUnderscore = false }
        else if !lastUnderscore { result.append("_"); lastUnderscore = true }
    }
    let safe = result.trimmingCharacters(in: CharacterSet(charactersIn: "_"))
    return "\(safe.isEmpty ? "schedule" : safe).ics"
}

/// `weekStartEpochDay` = days since 1970-01-01 (matches Kotlin LocalDate.toEpochDay()).
func buildScheduleIcs(
    scheduleName: String,
    enabledShifts: [String],
    grid: [[[String]]],
    weekStartEpochDay: Int
) -> String {
    let shifts = enabledShifts.isEmpty ? ["Shift"] : enabledShifts
    var out = ""
    out += "BEGIN:VCALENDAR\r\n"
    out += "VERSION:2.0\r\n"
    out += "PRODID:-//Scheduler Systems//Schedule Export//EN\r\n"
    out += "CALSCALE:GREGORIAN\r\n"
    out += "X-WR-CALNAME:\(icsEscape(scheduleName.trimmingCharacters(in: .whitespaces).isEmpty ? "Schedule" : scheduleName))\r\n"
    var cal = Calendar(identifier: .gregorian)
    cal.timeZone = TimeZone(identifier: "UTC")!
    let epoch = Date(timeIntervalSince1970: 0)
    var seq = 0
    for (dayIndex, dayShifts) in grid.enumerated() {
        let date = cal.date(byAdding: .day, value: weekStartEpochDay + dayIndex, to: epoch)!
        let next = cal.date(byAdding: .day, value: 1, to: date)!
        let c = cal.dateComponents([.year, .month, .day], from: date)
        let cn = cal.dateComponents([.year, .month, .day], from: next)
        let dateStr = String(format: "%04d%02d%02d", c.year!, c.month!, c.day!)
        let nextStr = String(format: "%04d%02d%02d", cn.year!, cn.month!, cn.day!)
        for s in shifts.indices {
            let names = (s < dayShifts.count ? dayShifts[s] : []).filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            for name in names {
                seq += 1
                out += "BEGIN:VEVENT\r\n"
                out += "UID:sched-\(dateStr)-\(s)-\(seq)@scheduler-systems\r\n"
                out += "DTSTART;VALUE=DATE:\(dateStr)\r\n"
                out += "DTEND;VALUE=DATE:\(nextStr)\r\n"
                out += "SUMMARY:\(icsEscape("\(shifts[s]) shift — \(name)"))\r\n"
                out += "DESCRIPTION:\(icsEscape("\(name) · \(shifts[s]) · \(icsDayLabels[dayIndex % 7])"))\r\n"
                out += "END:VEVENT\r\n"
            }
        }
    }
    out += "END:VCALENDAR\r\n"
    return out
}
