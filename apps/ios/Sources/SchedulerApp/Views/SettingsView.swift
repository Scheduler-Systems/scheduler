import SwiftUI

struct SettingsView: View {
    @StateObject private var vm: AuthViewModel
    @EnvironmentObject private var router: Router

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        List {
            Section("Account") {
                if let email = vm.currentUserEmail {
                    HStack {
                        Text("Email")
                        Spacer()
                        Text(email).foregroundColor(.secondary)
                    }
                }
                if let name = vm.currentUserDisplayName {
                    HStack {
                        Text("Name")
                        Spacer()
                        Text(name).foregroundColor(.secondary)
                    }
                }
            }

            Section {
                Button("Update Email") { /* Show sheet */ }
                Button("Change Password") { /* Show sheet */ }
            }

            Section {
                Button(role: .destructive) {
                    Task { await vm.signOut() }
                    router.replace(with: .login)
                } label: {
                    Text("Sign Out")
                }

                Button(role: .destructive) {
                    Task { await vm.deleteAccount() }
                    router.replace(with: .login)
                } label: {
                    Text("Delete Account")
                }
            }
        }
        .navigationTitle("Settings")
    }
}
