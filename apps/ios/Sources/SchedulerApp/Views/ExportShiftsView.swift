import SwiftUI

/// Export Shifts: previews the built schedule, exports it to a real iCalendar (.ics) file, and
/// shares it via the system share sheet (imports into Google Calendar + any calendar app).
/// Credential-free — replaces the Google-Calendar-OAuth path. Self-loading + self-sufficient.
struct ExportShiftsView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel

    @State private var scheduleName = ""
    @State private var enabledShifts: [String] = []
    @State private var grid: [[[String]]] = []
    @State private var isLoading = false
    @State private var isExporting = false
    @State private var icsURL: URL?
    @State private var eventCount = 0
    @State private var showShareSheet = false
    @State private var errorText: String?

    private let days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if isLoading {
                    HStack { ProgressView(); Text("Preparing schedule…") }
                } else {
                    Text("\(scheduleName.isEmpty ? "Untitled" : scheduleName) Schedule").font(.headline)

                    if let errorText {
                        Text("Error: \(errorText)").foregroundColor(.red).font(.caption)
                    }

                    if grid.isEmpty {
                        Text("No schedule built yet.").foregroundColor(.secondary)
                    } else {
                        Text("Preview").fontWeight(.semibold)
                        ForEach(Array(grid.enumerated()), id: \.offset) { dayIdx, dayShifts in
                            let assigned = Array(Set(dayShifts.flatMap { $0 }.filter { !$0.isEmpty })).sorted().joined(separator: ", ")
                            if !assigned.isEmpty {
                                HStack {
                                    Text(dayIdx < days.count ? days[dayIdx] : "?")
                                        .frame(width: 44, alignment: .leading).fontWeight(.medium)
                                    Text(assigned).font(.caption)
                                }
                            }
                        }
                    }

                    Button(action: export) {
                        if isExporting {
                            ProgressView()
                        } else {
                            Text("Export to Calendar")
                                .fontWeight(.semibold)
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.purple)
                                .foregroundColor(.white)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                    }
                    .disabled(isExporting || grid.isEmpty)

                    if icsURL != nil {
                        Text("Calendar file ready · \(eventCount) event(s)")
                            .font(.subheadline).fontWeight(.bold)
                        Button(action: { showShareSheet = true }) {
                            Text("Share")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.purple))
                        }
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Export Shifts")
        .task { await load() }
        .sheet(isPresented: $showShareSheet) {
            if let icsURL { ExportActivityView(items: [icsURL]) }
        }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { return }
        isLoading = true
        errorText = nil
        do {
            let schedule = try await scheduleService.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
            scheduleName = schedule.name
            enabledShifts = shiftLabels(schedule.settings)
            if let latest = try await scheduleService.latestBuiltSchedule(tenantId: tenantId, scheduleId: scheduleId),
               !latest.isEmpty {
                grid = latest
            } else {
                grid = try await scheduleService.buildAndSaveSchedule(tenantId: tenantId, scheduleId: scheduleId)
            }
        } catch {
            errorText = error.localizedDescription
        }
        isLoading = false
    }

    private func export() {
        isExporting = true
        let weekStart = Int(Date().timeIntervalSince1970 / 86400)
        let ics = buildScheduleIcs(scheduleName: scheduleName, enabledShifts: enabledShifts, grid: grid, weekStartEpochDay: weekStart)
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(scheduleIcsFilename(scheduleName: scheduleName))
        do {
            try ics.write(to: url, atomically: true, encoding: .utf8)
            eventCount = ics.components(separatedBy: "BEGIN:VEVENT").count - 1
            icsURL = url
        } catch {
            errorText = error.localizedDescription
        }
        isExporting = false
    }

    private func shiftLabels(_ settings: ScheduleSettings) -> [String] {
        var out: [String] = []
        if settings.mornings { out.append("Morning") }
        if settings.afternoons { out.append("Afternoon") }
        if settings.evenings { out.append("Night") }
        return out.isEmpty ? ["Morning", "Afternoon", "Night"] : out
    }
}

/// Thin UIKit bridge for the system share sheet (separate name from share-pdf's ActivityView).
private struct ExportActivityView: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
