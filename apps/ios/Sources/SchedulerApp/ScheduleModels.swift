import Foundation

struct ScheduleState: Identifiable {
    let id: String
    let tenantId: String
    let name: String
    let managerMode: ShellMode
    let workerMode: ShellMode
    let shifts: [ShiftState]
}

struct ShellMode {
    let label: String
}

struct ShiftState: Identifiable {
    let id: String
    let day: String
    let startTime: String
    let endTime: String
    let assignedWorker: String
}

enum MockSchedule {
    static let state = ScheduleState(
        id: "schedule_security_weekly",
        tenantId: "tenant_security_demo",
        name: "Security Weekly Roster",
        managerMode: ShellMode(label: "review drafts and approvals"),
        workerMode: ShellMode(label: "view shifts and submit availability"),
        shifts: [
            ShiftState(id: "shift_fri_morning", day: "Friday", startTime: "06:00", endTime: "14:00", assignedWorker: "Guard One"),
            ShiftState(id: "shift_sat_morning", day: "Saturday", startTime: "06:00", endTime: "14:00", assignedWorker: "Unassigned")
        ]
    )
}
