import SwiftUI

// Self-loading: lists the schedule's invitations (manager-sent add requests) from the
// Go API. Reached from the schedule dashboard's "Requests" button.
struct ScheduleRequestsView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var invitations: [Invitation] = []
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
            } else if invitations.isEmpty {
                Text("No requests").foregroundColor(.secondary)
            } else {
                List(invitations) { invitation in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(invitation.invitee).fontWeight(.semibold)
                        Text(invitation.statusLabel)
                            .font(.caption)
                            .foregroundColor(.orange)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .navigationTitle("Requests")
        .task {
            guard let tenantId = auth.currentUserId else { isLoading = false; return }
            do {
                invitations = try await scheduleService.fetchInvitations(tenantId: tenantId, scheduleId: scheduleId)
            } catch {
                loadError = error.localizedDescription
            }
            isLoading = false
        }
    }
}
