import SwiftUI

struct VerifyEmailView: View {
    @StateObject private var vm: AuthViewModel
    @EnvironmentObject private var router: Router

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: "envelope.badge")
                .resizable()
                .scaledToFit()
                .frame(width: 80, height: 80)
                .foregroundColor(.purple)

            Text("Verify Your Email")
                .font(.title2)
                .fontWeight(.bold)

            Text("We've sent a verification email to \(vm.currentUserEmail ?? "your email"). Please check your inbox and tap the link to continue.")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal)

            Button(action: { Task { await vm.sendEmailVerification() } }) {
                Label("Resend Email", systemImage: "arrow.clockwise")
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .padding(.horizontal)

            Button("I've verified my email") {
                Task {
                    if await vm.checkEmailVerified() {
                        router.replace(with: .home)
                    }
                }
            }

            if let error = vm.errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.red)
            }

            Spacer()
        }
        .onChange(of: vm.isAuthenticated) { authenticated in
            if !authenticated {
                router.replace(with: .login)
            }
        }
    }
}
