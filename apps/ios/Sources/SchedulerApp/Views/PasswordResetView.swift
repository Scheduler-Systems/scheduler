import SwiftUI

struct PasswordResetView: View {
    @StateObject private var vm: AuthViewModel

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 20) {
            Text("Reset Password")
                .font(.title)
                .fontWeight(.bold)

            Text("Enter your email and we'll send you a reset link")
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            TextField("Email", text: $vm.email)
                .textContentType(.emailAddress)
                #if os(iOS)
                .keyboardType(.emailAddress)
                .autocapitalization(.none)
                #endif
                .padding()
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .padding(.horizontal)

            switch vm.passwordResetState {
            case .sending:
                ProgressView("Sending...")
            case .sent:
                VStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                        .font(.title)
                    Text("Check your email for the reset link")
                }
            case .error(let msg):
                Text(msg).foregroundColor(.red).font(.caption)
            default:
                EmptyView()
            }

            Button(action: { Task { await vm.sendPasswordReset() } }) {
                Text("Send Reset Email")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.purple)
                    .foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .padding(.horizontal)
        }
    }
}
