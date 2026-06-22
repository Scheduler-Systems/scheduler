import SwiftUI

// Self-loading, read-only: lists the schedule's current priority standings
// (current_priorities from the Go API). Mirrors Android's CurrentPrioritiesScreen.
// Reached from the schedule dashboard's "Current Priorities" button.
struct CurrentPrioritiesView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var priorities: [String] = []
    @State private var isLoading = true
    @State private var loadError: String?

    init(scheduleId: String, scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleId = scheduleId
        self.scheduleService = scheduleService
    }

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
            } else if let loadError {
                Text(loadError).foregroundColor(.red)
            } else if priorities.isEmpty {
                Text("No priorities configured").foregroundColor(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 16) {
                    Text("Priority Standings").font(.title3.bold())
                    List(Array(priorities.enumerated()), id: \.offset) { index, name in
                        Text("\(index + 1). \(name)")
                    }
                }
                .padding()
            }
        }
        .navigationTitle("Current Priorities")
        .task { await load() }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { isLoading = false; return }
        do {
            let schedule = try await scheduleService.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
            priorities = schedule.currentPriorities
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }
}
