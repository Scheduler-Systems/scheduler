import SwiftUI

struct PhoneSignInView: View {
    @StateObject private var vm: AuthViewModel
    @EnvironmentObject private var router: Router

    init(authService: AuthServiceProtocol = AuthService.shared) {
        _vm = StateObject(wrappedValue: AuthViewModel(authService: authService))
    }

    var body: some View {
        VStack(spacing: 20) {
            Text("Phone Sign In")
                .font(.title)
                .fontWeight(.bold)

            if vm.phoneAuthState.isCodeSent {
                verificationStep
            } else {
                phoneEntryStep
            }

            if let error = vm.errorMessage {
                Text(error).font(.caption).foregroundColor(.red)
            }
        }
        .padding()
        .onChange(of: vm.isAuthenticated) { authenticated in
            if authenticated {
                router.replace(with: .home)
            }
        }
    }

    private var phoneEntryStep: some View {
        VStack(spacing: 16) {
            TextField("+1 (555) 555-5555", text: $vm.phoneNumber)
                .textContentType(.telephoneNumber)
                #if os(iOS)
                .keyboardType(.phonePad)
                #endif
                .padding()
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 10))

            Button(action: { Task { await vm.beginPhoneAuth() } }) {
                if vm.isLoading {
                    ProgressView()
                } else {
                    Text("Send Code")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.purple)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            .disabled(vm.isLoading)
        }
    }

    private var verificationStep: some View {
        VStack(spacing: 16) {
            Text("Enter verification code sent to \(vm.phoneAuthState.phoneNumber)")
                .multilineTextAlignment(.center)

            TextField("Verification Code", text: $vm.verificationCode)
                .textContentType(.oneTimeCode)
                #if os(iOS)
                .keyboardType(.numberPad)
                #endif
                .padding()
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 10))

            Button(action: { Task { await vm.verifyPhoneCode() } }) {
                if vm.isLoading {
                    ProgressView()
                } else {
                    Text("Verify")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.purple)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            .disabled(vm.isLoading)

            Button("Change Number") { vm.resetPhoneAuth() }
        }
    }
}
