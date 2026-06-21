import SwiftUI

struct CreateAccountView: View {
    @StateObject private var vm: AuthViewModel

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 20) {
            Text("Create Account")
                .font(.title)
                .fontWeight(.bold)

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
                    .textContentType(.newPassword)
                    .padding()
                    .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                SecureField("Confirm Password", text: $vm.confirmPassword)
                    .textContentType(.newPassword)
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

            Button(action: { Task { await vm.createAccountWithEmail() } }) {
                if vm.isLoading {
                    ProgressView()
                } else {
                    Text("Create Account")
                        .fontWeight(.semibold)
                }
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color.purple)
            .foregroundColor(.white)
            .clipShape(RoundedRectangle(cornerRadius: 10))
            .padding(.horizontal)
            .disabled(vm.isLoading)
        }
        // Post-auth routing (new unverified accounts → verify-email) is handled once,
        // centrally, by the root LoginView auth observer — no per-screen redirect here.
    }
}
