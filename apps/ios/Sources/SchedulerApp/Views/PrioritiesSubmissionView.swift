import SwiftUI

// Self-loading: fetches the schedule (tenant = current user id) and lists its ordered
// priority slots (current_priorities) with a checkbox each. Submit posts the selection
// to the Go API's /availability endpoint (202). Mirrors Android's PrioritiesSubmissionScreen.
// Reached from the schedule dashboard's "Submit Priorities" button.
struct PrioritiesSubmissionView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var priorities: [String] = []
    @State private var selected: [Bool] = []
    @State private var isLoading = true
    @State private var loadError: String?
    @State private var isSubmitting = false
    @State private var isSubmitted = false
    @State private var submitError: String?

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
                    Text("Priority Order").font(.title3.bold())
                    List {
                        ForEach(Array(priorities.enumerated()), id: \.offset) { index, name in
                            Toggle("\(index + 1). \(name)", isOn: binding(for: index))
                        }
                    }
                    if isSubmitted {
                        Text("Priorities submitted!").foregroundColor(.green).fontWeight(.medium)
                    }
                    if let submitError {
                        Text(submitError).foregroundColor(.red)
                    }
                    Button(action: submit) {
                        Text(isSubmitting ? "Submitting…" : "Submit")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isSubmitting)
                    .accessibilityIdentifier("submitPrioritiesButton")
                }
                .padding()
            }
        }
        .navigationTitle("Submit Priorities")
        .task { await load() }
    }

    private func binding(for index: Int) -> Binding<Bool> {
        Binding(
            get: { selected.indices.contains(index) ? selected[index] : false },
            set: { if selected.indices.contains(index) { selected[index] = $0 } }
        )
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { isLoading = false; return }
        do {
            let schedule = try await scheduleService.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
            priorities = schedule.currentPriorities
            selected = Array(repeating: false, count: priorities.count)
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }

    private func submit() {
        guard let tenantId = auth.currentUserId else { submitError = "Not signed in"; return }
        isSubmitting = true
        submitError = nil
        let selectedNames = priorities.enumerated()
            .filter { selected.indices.contains($0.offset) && selected[$0.offset] }
            .map { $0.element }
        let availability: [String: String] = [
            "priorities": priorities.joined(separator: ","),
            "selected": selectedNames.joined(separator: ",")
        ]
        Task {
            do {
                try await scheduleService.submitAvailability(tenantId: tenantId, scheduleId: scheduleId, availability: availability)
                isSubmitted = true
            } catch {
                submitError = error.localizedDescription
            }
            isSubmitting = false
        }
    }
}
