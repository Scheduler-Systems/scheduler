import SwiftUI

struct LoginView: View {
    @StateObject private var vm: AuthViewModel
    @EnvironmentObject private var router: Router

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 20) {
            Spacer()

            Text("Scheduler")
                .font(.largeTitle)
                .fontWeight(.bold)
                .foregroundColor(.purple)

            Text("Sign in to manage your schedules")
                .foregroundColor(.secondary)

            VStack(spacing: 12) {
                TextField("Email", text: $vm.email)
                    .textContentType(.emailAddress)
                    #if os(iOS)
                    .keyboardType(.emailAddress)
                    .autocapitalization(.none)
                    #endif
                    .padding()
                    .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                SecureField("Password", text: $vm.password)
                    .textContentType(.password)
                    .padding()
                    .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .padding(.horizontal)

            if let error = vm.errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.red)
            }

            VStack(spacing: 12) {
                Button(action: { Task { await vm.signInWithEmail() } }) {
                    if vm.isLoading {
                        ProgressView()
                    } else {
                        Text("Sign In")
                            .fontWeight(.semibold)
                    }
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.purple)
                .foregroundColor(.white)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .disabled(vm.isLoading)

                Button(action: { router.push(.createAccount) }) {
                    Text("Create Account")
                        .fontWeight(.medium)
                }

                Button(action: { router.push(.passwordReset) }) {
                    Text("Forgot Password?")
                        .font(.caption)
                }
            }
            .padding(.horizontal)

            Divider().padding(.horizontal)

            VStack(spacing: 12) {
                Button(action: { Task { await vm.signInWithGoogle() } }) {
                    Label("Continue with Google", systemImage: "g.circle")
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                Button(action: { Task { await vm.signInWithApple() } }) {
                    Label("Continue with Apple", systemImage: "apple.logo")
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            .padding(.horizontal)

            Spacer()
        }
        .onChange(of: vm.isAuthenticated) { authenticated in
            if authenticated {
                // Single post-auth gate for the whole stack (login OR signup, since this root
                // view observes the shared auth state). Parity with Flutter login → verify-email
                // → home: unverified users must verify their email before reaching home.
                if vm.currentUser?.isEmailVerified == true {
                    router.replace(with: .home)
                } else {
                    router.replace(with: .verifyEmail)
                }
            }
        }
    }
}
