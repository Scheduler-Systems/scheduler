import SwiftUI

// Self-loading: lists the signed-in user's notification feed from the Go API.
// Reached from Home (the bell button). Mirrors Android's NotificationsScreen.
struct NotificationsView: View {
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var notifications: [NotificationResponse] = []
    @State private var isLoading = true
    @State private var loadError: String?

    init(scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleService = scheduleService
    }

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
            } else if let loadError {
                Text(loadError).foregroundColor(.red)
            } else if notifications.isEmpty {
                Text("No notifications").foregroundColor(.secondary)
            } else {
                List(notifications) { n in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(n.content ?? "")
                            .fontWeight((n.isRead ?? false) ? .regular : .semibold)
                        Text((n.type ?? "SYSTEM").replacingOccurrences(of: "_", with: " ").capitalized)
                            .font(.caption)
                            .foregroundColor(.purple)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .navigationTitle("Notifications")
        .task { await load() }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else { isLoading = false; return }
        do {
            notifications = try await scheduleService.fetchNotifications(tenantId: tenantId)
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }
}
