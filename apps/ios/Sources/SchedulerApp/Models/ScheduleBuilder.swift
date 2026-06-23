import Foundation

/// Priority-aware schedule builder — a faithful Swift port of the production web
/// algorithm (scheduler-web/lib/schedule-builder.ts buildSchedule), identical to the
/// Android Kotlin port. Parity is pinned by ScheduleBuilderTests (the web's own test
/// cases as golden outputs), so web ↔ Android ↔ iOS all agree.
///
/// Pick order for each slot:
///   1. Workers who marked this exact (weekday|shift) cell as priority AND (if
///      avoidSameDayConflicts) aren't already on that day. Fewest assignments wins.
///   2. Otherwise fairness round-robin: least-assigned eligible worker, tie-break on
///      cursor-relative order.
/// Output `rows` is day-major: rows[dayIdx * numShifts + shiftIdx] = the names for that
/// slot (one per station).

struct BuildScheduleInput {
    let employees: [String]
    let enabledShifts: [String]
    let numDays: Int
    let numStations: Int
    var startWeekday: Int = 0 // 0 = Sunday (matches Date.getUTCDay())
    var avoidSameDayConflicts: Bool = false
    var priorities: [String: Set<String>] = [:]
}

struct ScheduleConflict: Equatable {
    let dayIndex: Int
    let worker: String
    let shifts: [String]
}

struct BuildScheduleOutput: Equatable {
    let rows: [[String]]
    let conflicts: [ScheduleConflict]
}

private let kWeekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

private func normName(_ s: String) -> String {
    s.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
}

func buildSchedule(_ input: BuildScheduleInput) -> BuildScheduleOutput {
    let employees = input.employees
    let enabledShifts = input.enabledShifts
    guard input.numDays > 0, !enabledShifts.isEmpty else {
        return BuildScheduleOutput(rows: [], conflicts: [])
    }

    var normalizedPriorities: [String: Set<String>] = [:]
    for (k, v) in input.priorities { normalizedPriorities[normName(k)] = v }

    let n = employees.count
    var assignments: [Int: Int] = [:]
    var rows: [[String]] = []
    var cursor = 0

    func relativeOrder(_ a: Int, _ b: Int) -> Int {
        ((a - cursor + n) % n) - ((b - cursor + n) % n)
    }

    func pickIndex(_ cellKey: String, _ dayAssigned: Set<String>) -> Int? {
        if n == 0 { return nil }

        // 1. Priority candidates: marked this cell AND eligible.
        var priorityIdxs: [Int] = []
        for i in 0..<n {
            guard let cell = normalizedPriorities[normName(employees[i])] else { continue }
            if !cell.contains(cellKey) { continue }
            if input.avoidSameDayConflicts && dayAssigned.contains(employees[i]) { continue }
            priorityIdxs.append(i)
        }
        if !priorityIdxs.isEmpty {
            return priorityIdxs.sorted { a, b in
                let ca = assignments[a] ?? 0, cb = assignments[b] ?? 0
                if ca != cb { return ca < cb }
                return relativeOrder(a, b) < 0
            }.first
        }

        // 2. Fairness fallback: least-assigned eligible worker, cursor-relative tie-break.
        var candidateIdxs: [Int] = []
        for offset in 0..<n {
            let i = (cursor + offset) % n
            if input.avoidSameDayConflicts && dayAssigned.contains(employees[i]) { continue }
            candidateIdxs.append(i)
        }
        if candidateIdxs.isEmpty { return nil }
        return candidateIdxs.sorted { a, b in
            let ca = assignments[a] ?? 0, cb = assignments[b] ?? 0
            if ca != cb { return ca < cb }
            return relativeOrder(a, b) < 0
        }.first
    }

    for d in 0..<input.numDays {
        let weekday = kWeekdays[(input.startWeekday + d) % 7]
        var dayAssigned = Set<String>()
        for s in 0..<enabledShifts.count {
            let cellKey = "\(weekday)|\(enabledShifts[s])"
            var stringList: [String] = []
            for _ in 0..<input.numStations {
                guard let idx = pickIndex(cellKey, dayAssigned) else {
                    stringList.append("")
                    continue
                }
                let pick = employees[idx]
                stringList.append(pick)
                dayAssigned.insert(pick)
                assignments[idx] = (assignments[idx] ?? 0) + 1
                cursor = (idx + 1) % n
            }
            rows.append(stringList)
        }
    }

    // Conflict detection: a worker on >1 shift the same day.
    var conflicts: [ScheduleConflict] = []
    let numShifts = enabledShifts.count
    for d in 0..<input.numDays {
        var seen: [String: [String]] = [:]
        var order: [String] = []
        for s in 0..<numShifts {
            let row = rows[d * numShifts + s]
            for name in row where !name.isEmpty {
                if seen[name] != nil {
                    if !seen[name]!.contains(enabledShifts[s]) { seen[name]!.append(enabledShifts[s]) }
                } else {
                    seen[name] = [enabledShifts[s]]
                    order.append(name)
                }
            }
        }
        for worker in order where (seen[worker]?.count ?? 0) > 1 {
            conflicts.append(ScheduleConflict(dayIndex: d, worker: worker, shifts: seen[worker]!))
        }
    }

    return BuildScheduleOutput(rows: rows, conflicts: conflicts)
}
