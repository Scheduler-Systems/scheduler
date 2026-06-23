import SwiftUI

struct ScheduleDashboardView: View {
    @EnvironmentObject private var router: Router
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
                    Button(action: { router.push(.employeeList(schedule.id)) }) {
                        Label("Employee List & Requests", systemImage: "person.3")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.scheduleSettings(schedule.id)) }) {
                        Label("Schedule Settings", systemImage: "gearshape")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.scheduleRequests(schedule.id)) }) {
                        Label("Schedule Requests", systemImage: "envelope")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.prioritiesSubmission(schedule.id)) }) {
                        Label("Submit Priorities", systemImage: "list.number")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.currentPriorities(schedule.id)) }) {
                        Label("Current Priorities", systemImage: "list.star")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.scheduleBuild(schedule.id)) }) {
                        Label("Build Schedule", systemImage: "calendar.badge.plus")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    sharePdfButton
                }
            }
            .padding()
        }
        .navigationTitle("Schedule Detail")
    }

    // Extracted to keep the action-button VStack expression small enough for the
    // Swift type-checker (a 7th inline styled button tipped it over the limit).
    private var sharePdfButton: some View {
        Button(action: { router.push(.sharePdf(schedule.id)) }) {
            Label("Share PDF", systemImage: "square.and.arrow.up")
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.purple)
                .foregroundColor(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10))
        }
    }

    private var attendancePercent: Int {
        let assigned = schedule.shifts.filter { $0.assignedWorkerId != nil }.count
        guard !schedule.shifts.isEmpty else { return 0 }
        return Int(Double(assigned) / Double(schedule.shifts.count) * 100)
    }
}
