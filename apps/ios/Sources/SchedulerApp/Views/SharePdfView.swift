import SwiftUI

/// Share PDF: previews the built schedule (the real assigned roster), generates an
/// on-device PDF of it (UIGraphicsPDFRenderer), and shares the file via the system
/// share sheet. Self-loading and self-sufficient — if no built schedule exists yet
/// it builds one first, so there is always something real to export.
struct SharePdfView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel

    @State private var scheduleName = ""
    @State private var enabledShifts: [String] = []
    @State private var grid: [[[String]]] = []
    @State private var isLoading = false
    @State private var isGenerating = false
    @State private var rendered: RenderedSchedulePdf?
    @State private var showShareSheet = false
    @State private var errorText: String?

    private let days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if isLoading {
                    HStack { ProgressView(); Text("Preparing schedule…") }
                } else {
                    Text("\(scheduleName.isEmpty ? "Untitled" : scheduleName) Schedule")
                        .font(.headline)

                    if let errorText {
                        Text("Error: \(errorText)").foregroundColor(.red).font(.caption)
                    }

                    if grid.isEmpty {
                        Text("No schedule built yet.").foregroundColor(.secondary)
                    } else {
                        Text("Preview").fontWeight(.semibold)
                        // One line per day with at least one assignment.
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

                    Button(action: generate) {
                        if isGenerating {
                            ProgressView()
                        } else {
                            Text("Generate PDF")
                                .fontWeight(.semibold)
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.purple)
                                .foregroundColor(.white)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        }
                    }
                    .disabled(isGenerating || grid.isEmpty)

                    if let rendered {
                        Text("PDF ready · \(rendered.pageCount) page(s)")
                            .font(.subheadline).fontWeight(.bold)
                        Button(action: { showShareSheet = true }) {
                            Text("Share PDF")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.purple))
                        }
                    }
                }
            }
            .padding()
        }
        .navigationTitle("Share PDF")
        .task { await load() }
        .sheet(isPresented: $showShareSheet) {
            if let rendered {
                ActivityView(items: [rendered.url])
            }
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
            // Ensure there is something to share: latest built grid, else build one.
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

    private func generate() {
        let doc = buildSchedulePdfDoc(scheduleName: scheduleName, enabledShifts: enabledShifts, grid: grid)
        isGenerating = true
        Task {
            let result = SchedulePdfRenderer.render(doc)
            await MainActor.run {
                rendered = result
                isGenerating = false
            }
        }
    }

    private func shiftLabels(_ settings: ScheduleSettings) -> [String] {
        var out: [String] = []
        if settings.mornings { out.append("Morning") }
        if settings.afternoons { out.append("Afternoon") }
        if settings.evenings { out.append("Night") }
        return out.isEmpty ? ["Morning", "Afternoon", "Night"] : out
    }
}

/// Thin UIKit bridge for the system share sheet.
private struct ActivityView: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }
    func updateUIViewController(_ controller: UIActivityViewController, context: Context) {}
}
