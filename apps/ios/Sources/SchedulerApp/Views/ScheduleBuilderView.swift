import SwiftUI

struct ScheduleBuilderView: View {
    let scheduleService: ScheduleDataServiceProtocol
    @State private var name = ""
    @State private var startDate = Date()
    @State private var endDate = Date().addingTimeInterval(7 * 86400)
    @State private var shifts: [Shift] = []
    @State private var isCreating = false
    @State private var createError: String?
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var auth: AuthViewModel

    init(scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleService = scheduleService
    }

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
                    Text(isCreating ? "Creating…" : "Create Schedule")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .foregroundColor(.white)
                }
                .listRowBackground(Color.purple)
                .disabled(name.isEmpty || isCreating)
                if let createError {
                    Text(createError).foregroundColor(.red).font(.caption)
                }
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
        guard let tenantId = auth.currentUserId else {
            createError = "Not signed in"
            return
        }
        let schedule = Schedule(
            id: UUID().uuidString,
            tenantId: tenantId,
            name: name,
            startDate: startDate,
            endDate: endDate,
            shifts: shifts,
            status: .draft,
            createdAt: Date(),
            updatedAt: Date()
        )
        isCreating = true
        createError = nil
        Task {
            do {
                _ = try await scheduleService.createSchedule(tenantId: tenantId, schedule: schedule)
                isCreating = false
                router.pop()
            } catch {
                isCreating = false
                createError = error.localizedDescription
            }
        }
    }
}
