import SwiftUI

// Auth onboarding step 2: persist the chosen role (PUT /users/{uid}/role), then go home.
// Reached from get-name (parity with Flutter's getName → chooseRole chain).
struct ChooseRoleView: View {
    let scheduleService: ScheduleDataServiceProtocol
    @StateObject private var vm = ChooseRoleViewModel()
    @State private var isSaving = false
    @State private var saveError: String?
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var auth: AuthViewModel

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Text("Choose Your Role")
                .font(.title)
                .fontWeight(.bold)

            Text("Choose your role, so that we personalize your experience")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            Image(systemName: "person.2")
                .resizable()
                .scaledToFit()
                .frame(height: 180)
                .foregroundColor(.purple.opacity(0.3))

            if let saveError {
                Text(saveError).foregroundColor(.red).font(.caption)
            }

            Spacer()

            VStack(spacing: 16) {
                Button(action: { selectRole(isManager: true) }) {
                    Text(isSaving ? "Saving…" : "Log In as Manager")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.purple)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .disabled(isSaving)

                Button(action: { selectRole(isManager: false) }) {
                    Text(isSaving ? "Saving…" : "Log In as Employee")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.pink)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .disabled(isSaving)
            }
            .padding(.horizontal, 16)

            Spacer()
        }
        .navigationTitle("Choose Role")
    }

    private func selectRole(isManager: Bool) {
        if isManager { vm.selectManager() } else { vm.selectEmployee() }
        guard let uid = auth.currentUserId else { router.push(.home); return }
        isSaving = true
        saveError = nil
        Task {
            do {
                try await scheduleService.updateRole(
                    tenantId: uid, uid: uid, email: auth.currentUserEmail ?? "", isManager: isManager
                )
                isSaving = false
                router.push(.home)
            } catch {
                isSaving = false
                saveError = error.localizedDescription
            }
        }
    }
}
