import SwiftUI

// Self-loading per-schedule settings editor: fetch the schedule (tenant = current user id),
// edit the enabled-shift toggles + timezone, and save via the Go API
// (PUT /schedules/{id} with nested settings). Reached from the schedule dashboard.
struct ScheduleSettingsView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var schedule: Schedule?
    @State private var mornings = false
    @State private var afternoons = false
    @State private var evenings = false
    @State private var timezone = "UTC"
    @State private var isLoading = true
    @State private var isSaving = false
    @State private var saved = false
    @State private var loadError: String?
    @State private var saveError: String?

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
            } else {
                Form {
                    Section("Enabled Shifts") {
                        Toggle("Mornings", isOn: $mornings)
                        Toggle("Afternoons", isOn: $afternoons)
                        Toggle("Evenings", isOn: $evenings)
                    }
                    Section {
                        Button(action: save) {
                            Text(isSaving ? "Saving…" : "Save Settings")
                                .frame(maxWidth: .infinity)
                        }
                        .disabled(isSaving)
                        if saved { Text("Settings saved").foregroundColor(.green).font(.caption) }
                        if let saveError { Text(saveError).foregroundColor(.red).font(.caption) }
                    }
                }
            }
        }
        .navigationTitle("Schedule Settings")
        .task { await load() }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { isLoading = false; return }
        do {
            let s = try await scheduleService.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
            schedule = s
            mornings = s.settings.mornings
            afternoons = s.settings.afternoons
            evenings = s.settings.evenings
            timezone = s.settings.timezone
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    private func save() {
        guard let tenantId = auth.currentUserId, var updated = schedule else { return }
        updated.settings = ScheduleSettings(mornings: mornings, afternoons: afternoons, evenings: evenings, timezone: timezone)
        isSaving = true; saved = false; saveError = nil
        Task {
            do {
                _ = try await scheduleService.updateSchedule(tenantId: tenantId, schedule: updated)
                schedule = updated
                isSaving = false
                saved = true
            } catch {
                isSaving = false
                saveError = error.localizedDescription
            }
        }
    }
}
