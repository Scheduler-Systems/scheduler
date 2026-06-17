import SwiftUI

struct ProfileView: View {
    @StateObject private var vm: AuthViewModel
    @EnvironmentObject private var router: Router

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "person.circle.fill")
                .resizable()
                .frame(width: 100, height: 100)
                .foregroundColor(.purple)

            Text(vm.currentUserDisplayName ?? "User")
                .font(.title)
                .fontWeight(.bold)

            if let email = vm.currentUserEmail {
                Text(email).foregroundColor(.secondary)
            }

            Spacer()
        }
        .padding(.top, 40)
        .navigationTitle("Profile")
    }
}
