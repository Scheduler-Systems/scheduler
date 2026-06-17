import SwiftUI

struct ScheduleDashboardView: View {
    @StateObject private var vm: ScheduleViewModel
    let schedule: Schedule

    init(schedule: Schedule, scheduleService: ScheduleDataServiceProtocol) {
        self.schedule = schedule
        _vm = StateObject(wrappedValue: ScheduleViewModel(scheduleService: scheduleService))
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    Text("Schedule Name:").fontWeight(.medium)
                    Text(schedule.name).fontWeight(.bold)
                }

                if !schedule.shifts.isEmpty {
                    Text("Statistics").font(.headline)

                    Text("Schedule Count: \(schedule.shifts.count)")

                    Text("Attendance: \(attendancePercent)%")

                    VStack(alignment: .leading, spacing: 8) {
                        Text("Shifts").font(.headline)
                        ForEach(schedule.shifts) { shift in
                            HStack {
                                Text(shift.dayOfWeek.rawValue.capitalized)
                                    .frame(width: 100, alignment: .leading)
                                Text("\(shift.startTime)-\(shift.endTime)")
                                Spacer()
                                Text(shift.assignedWorkerId ?? "Unassigned")
                                    .foregroundColor(.secondary)
                            }
                            .font(.subheadline)
                            .padding(.vertical, 4)
                            Divider()
                        }
                    }
                }

                VStack(spacing: 12) {
                    Button(action: {}) {
                        Label("Employee List & Requests", systemImage: "person.3")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Schedule Detail")
    }

    private var attendancePercent: Int {
        let assigned = schedule.shifts.filter { $0.assignedWorkerId != nil }.count
        guard !schedule.shifts.isEmpty else { return 0 }
        return Int(Double(assigned) / Double(schedule.shifts.count) * 100)
    }
}
