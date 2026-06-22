import SwiftUI

// Auth onboarding step 1: persist the display name (PUT /users/{uid}), then continue to
// choose-role. Reached from Home (parity with Flutter's pushNamedAuth(GetName) from home).
struct GetNameView: View {
    let scheduleService: ScheduleDataServiceProtocol
    @State private var name = ""
    @State private var isSaving = false
    @State private var saveError: String?
    @EnvironmentObject private var router: Router
    @EnvironmentObject private var auth: AuthViewModel

    var body: some View {
        VStack(spacing: 24) {
            Text("What should we call you?")
                .font(.title2)
                .fontWeight(.semibold)

            TextField("Your name", text: $name)
                .textContentType(.name)
                .padding()
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .padding(.horizontal)
                .accessibilityIdentifier("nameField")

            if let saveError {
                Text(saveError).foregroundColor(.red).font(.caption)
            }

            Button(action: save) {
                Text(isSaving ? "Saving…" : "Continue")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(name.isEmpty ? Color.gray : Color.purple)
                    .foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .disabled(name.isEmpty || isSaving)
            .padding(.horizontal)
        }
        .navigationTitle("Your Name")
    }

    private func save() {
        guard let uid = auth.currentUserId else { router.push(.chooseRole); return }
        isSaving = true
        saveError = nil
        Task {
            do {
                try await scheduleService.updateDisplayName(
                    tenantId: uid, uid: uid, email: auth.currentUserEmail ?? "", name: name
                )
                isSaving = false
                router.push(.chooseRole)
            } catch {
                isSaving = false
                saveError = error.localizedDescription
            }
        }
    }
}
