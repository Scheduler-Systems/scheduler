import SwiftUI

/// Schedule Build: runs the canonical schedule builder for a schedule (same algorithm as
/// Android + the web — see ScheduleBuilder.swift), persists the grid via the Go API, and
/// renders it. Self-loading: shows the latest built grid if one exists.
struct ScheduleBuildView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel

    @State private var grid: [[[String]]] = []
    @State private var isLoading = false
    @State private var loadError: String?

    private let days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
    private let shiftLabels = ["Morning", "Afternoon", "Night"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Button(action: build) {
                    if isLoading {
                        ProgressView()
                    } else {
                        Text("Generate Schedule")
                            .fontWeight(.semibold)
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
                .disabled(isLoading)

                if let loadError {
                    Text("Error: \(loadError)").foregroundColor(.red).font(.caption)
                }

                if grid.isEmpty {
                    if !isLoading {
                        Text("No schedule built yet. Tap Build Schedule to generate one.")
                            .foregroundColor(.secondary)
                    }
                } else {
                    Text("Built Schedule").font(.headline)
                    // Header row.
                    HStack {
                        Text("Day").frame(width: 44, alignment: .leading).fontWeight(.semibold)
                        ForEach(shiftLabels, id: \.self) { label in
                            Text(label).frame(maxWidth: .infinity, alignment: .leading)
                                .font(.caption).fontWeight(.semibold)
                        }
                    }
                    // grid is day-major: grid[day][shift] = the station name(s) for that slot.
                    ForEach(Array(grid.enumerated()), id: \.offset) { dayIdx, dayShifts in
                        HStack {
                            Text(dayIdx < days.count ? days[dayIdx] : "?")
                                .frame(width: 44, alignment: .leading)
                            ForEach(0..<shiftLabels.count, id: \.self) { shiftIdx in
                                let cell = (shiftIdx < dayShifts.count ? dayShifts[shiftIdx] : [])
                                    .filter { !$0.isEmpty }.joined(separator: ", ")
                                Text(cell.isEmpty ? "—" : cell)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Build Schedule")
        .task { await load() }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { return }
        if let latest = try? await scheduleService.latestBuiltSchedule(tenantId: tenantId, scheduleId: scheduleId) {
            grid = latest
        }
    }

    private func build() {
        guard let tenantId = auth.currentUserId else { return }
        isLoading = true
        loadError = nil
        Task {
            do {
                grid = try await scheduleService.buildAndSaveSchedule(tenantId: tenantId, scheduleId: scheduleId)
            } catch {
                loadError = error.localizedDescription
            }
            isLoading = false
        }
    }
}
