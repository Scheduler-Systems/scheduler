import SwiftUI

// Self-loading: fetches the tenant's schedules from the Go API and shows the ones with
// status == .archived. Reuses the existing schedules endpoint (no separate archived
// endpoint); the active list (My Schedules) and this view differ only by the status filter.
struct ArchivedSchedulesView: View {
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var schedules: [Schedule] = []
    @State private var isLoading = true
    @State private var loadError: String?

    init(scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleService = scheduleService
    }

    private var archived: [Schedule] { schedules.filter { $0.status == .archived } }

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
            } else if let loadError {
                Text(loadError).foregroundColor(.red)
            } else if archived.isEmpty {
                Text("No archived schedules").foregroundColor(.secondary)
            } else {
                List(archived) { schedule in
                    Text(schedule.name).fontWeight(.semibold)
                }
            }
        }
        .navigationTitle("Archived Schedules")
        .task {
            guard let tenantId = auth.currentUserId else {
                isLoading = false
                return
            }
            do {
                schedules = try await scheduleService.fetchSchedules(tenantId: tenantId)
                loadError = nil
            } catch {
                loadError = error.localizedDescription
            }
            isLoading = false
        }
    }
}
