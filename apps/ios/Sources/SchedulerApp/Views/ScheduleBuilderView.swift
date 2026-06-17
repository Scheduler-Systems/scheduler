import SwiftUI

struct ScheduleBuilderView: View {
    @State private var name = ""
    @State private var startDate = Date()
    @State private var endDate = Date().addingTimeInterval(7 * 86400)
    @State private var shifts: [Shift] = []
    @EnvironmentObject private var router: Router

    var onSave: ((Schedule) -> Void)?

    var body: some View {
        Form {
            Section("Schedule Details") {
                TextField("Schedule Name", text: $name)
                DatePicker("Start Date", selection: $startDate, displayedComponents: .date)
                DatePicker("End Date", selection: $endDate, displayedComponents: .date)
            }

            Section("Shifts") {
                ForEach($shifts) { $shift in
                    shiftRow($shift)
                }
                .onDelete(perform: shiftCount > 0 ? { _ in } : nil)

                Button(action: addShift) {
                    Label("Add Shift", systemImage: "plus")
                }
            }

            Section {
                Button(action: buildSchedule) {
                    Text("Create Schedule")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .foregroundColor(.white)
                }
                .listRowBackground(Color.purple)
                .disabled(name.isEmpty || shifts.isEmpty)
            }
        }
        .navigationTitle("New Schedule")
    }

    private func shiftRow(_ shift: Binding<Shift>) -> some View {
        VStack {
            Picker("Day", selection: shift.dayOfWeek) {
                ForEach(DayOfWeek.allCases, id: \.self) { day in
                    Text(day.rawValue.capitalized).tag(day)
                }
            }
            HStack {
                TextField("Start", text: shift.startTime)
                Text("-")
                TextField("End", text: shift.endTime)
            }
        }
    }

    private func addShift() {
        shifts.append(Shift(
            id: UUID().uuidString,
            scheduleId: "",
            dayOfWeek: .monday,
            startTime: "09:00",
            endTime: "17:00",
            assignedWorkerId: nil,
            stationId: nil,
            notes: nil
        ))
    }

    private var shiftCount: Int { shifts.count }

    private func buildSchedule() {
        let schedule = Schedule(
            id: UUID().uuidString,
            tenantId: "",
            name: name,
            startDate: startDate,
            endDate: endDate,
            shifts: shifts,
            status: .draft,
            createdAt: Date(),
            updatedAt: Date()
        )
        onSave?(schedule)
        router.pop()
    }
}
