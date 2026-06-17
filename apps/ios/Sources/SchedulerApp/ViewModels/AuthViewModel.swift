import Foundation
import FirebaseAuth
import Combine

@MainActor
final class AuthViewModel: ObservableObject {
    @Published private(set) var authState: AuthState = .unauthenticated
    @Published var email: String = ""
    @Published var password: String = ""
    @Published var confirmPassword: String = ""
    @Published var phoneNumber: String = ""
    @Published var verificationCode: String = ""
    @Published var phoneAuthState: PhoneAuthState = PhoneAuthState()
    @Published var passwordResetState: PasswordResetState = .idle
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?
    
    private let authService: AuthServiceProtocol
    private var cancellables = Set<AnyCancellable>()
    
    init(authService: AuthServiceProtocol = AuthService.shared) {
        self.authService = authService
        observeAuthState()
    }
    
    private func observeAuthState() {
        authService.authStatePublisher
            .receive(on: DispatchQueue.main)
            .sink { [weak self] state in
                self?.authState = state
                self?.isLoading = state.isLoading
            }
            .store(in: &cancellables)
    }
    
    var currentUser: AuthUser? {
        authState.user
    }
    
    var isAuthenticated: Bool {
        authState.isAuthenticated
    }
    
    var currentUserId: String? {
        currentUser?.id
    }
    
    var currentUserEmail: String? {
        currentUser?.email
    }
    
    var currentUserDisplayName: String? {
        currentUser?.displayName
    }
    
    func signInWithEmail() async {
        guard !email.isEmpty, !password.isEmpty else {
            errorMessage = "Please enter email and password"
            return
        }
        
        isLoading = true
        errorMessage = nil
        
        do {
            try await authService.signInWithEmail(email: email.trimmingCharacters(in: .whitespaces), password: password)
            clearForm()
        } catch {
            handleError(error)
        }
        
        isLoading = false
    }
    
    func createAccountWithEmail() async {
        guard !email.isEmpty, !password.isEmpty else {
            errorMessage = "Please enter email and password"
            return
        }
        
        guard password == confirmPassword else {
            errorMessage = "Passwords do not match"
            return
        }
        
        guard password.count >= 6 else {
            errorMessage = "Password must be at least 6 characters"
            return
        }
        
        isLoading = true
        errorMessage = nil
        
        do {
            try await authService.createAccountWithEmail(email: email.trimmingCharacters(in: .whitespaces), password: password)
            clearForm()
        } catch {
            handleError(error)
        }
        
        isLoading = false
    }
    
    func signInWithGoogle() async {
        isLoading = true
        errorMessage = nil
        
        do {
            try await authService.signInWithGoogle()
        } catch {
            handleError(error)
        }
        
        isLoading = false
    }
    
    func signInWithApple() async {
        isLoading = true
        errorMessage = nil
        
        do {
            try await authService.signInWithApple()
        } catch {
            handleError(error)
        }
        
        isLoading = false
    }
    
    func beginPhoneAuth() async {
        guard !phoneNumber.isEmpty else {
            errorMessage = "Please enter a phone number"
            return
        }
        
        let formattedNumber = formatPhoneNumber(phoneNumber)
        
        isLoading = true
        errorMessage = nil
        
        do {
            let verificationID = try await authService.beginPhoneAuth(phoneNumber: formattedNumber)
            phoneAuthState = PhoneAuthState(
                verificationID: verificationID,
                isCodeSent: true,
                phoneNumber: formattedNumber
            )
        } catch {
            handleError(error)
            phoneAuthState.error = error as? AuthError ?? .phoneAuthFailed(error.localizedDescription)
        }
        
        isLoading = false
    }
    
    func verifyPhoneCode() async {
        guard let verificationID = phoneAuthState.verificationID, !verificationCode.isEmpty else {
            errorMessage = "Please enter the verification code"
            return
        }
        
        isLoading = true
        errorMessage = nil
        
        do {
            try await authService.verifyPhoneCode(verificationID: verificationID, code: verificationCode)
            resetPhoneAuth()
        } catch {
            handleError(error)
        }
        
        isLoading = false
    }
    
    func sendPasswordReset() async {
        guard !email.isEmpty else {
            errorMessage = "Please enter your email"
            return
        }
        
        passwordResetState = .sending
        
        do {
            try await authService.sendPasswordReset(email: email.trimmingCharacters(in: .whitespaces))
            passwordResetState = .sent
        } catch {
            passwordResetState = .error(error.localizedDescription)
        }
    }
    
    func signOut() async {
        do {
            try await authService.signOut()
            clearForm()
        } catch {
            handleError(error)
        }
    }
    
    func deleteAccount() async {
        do {
            try await authService.deleteAccount()
            clearForm()
        } catch {
            handleError(error)
        }
    }
    
    func updateEmail(newEmail: String) async {
        do {
            try await authService.updateEmail(newEmail: newEmail)
        } catch {
            handleError(error)
        }
    }
    
    func updatePassword(newPassword: String) async {
        do {
            try await authService.updatePassword(newPassword: newPassword)
        } catch {
            handleError(error)
        }
    }
    
    func sendEmailVerification() async {
        do {
            try await authService.sendEmailVerification()
        } catch {
            handleError(error)
        }
    }
    
    func clearError() {
        errorMessage = nil
    }
    
    func clearForm() {
        email = ""
        password = ""
        confirmPassword = ""
        phoneNumber = ""
        verificationCode = ""
        errorMessage = nil
    }
    
    func resetPhoneAuth() {
        phoneAuthState = PhoneAuthState()
        verificationCode = ""
    }
    
    private func handleError(_ error: Error) {
        if let authError = error as? AuthError {
            errorMessage = authError.errorDescription
        } else {
            errorMessage = error.localizedDescription
        }
    }
    
    private func formatPhoneNumber(_ number: String) -> String {
        let digits = number.filter { $0.isNumber }
        if number.hasPrefix("+") {
            return "+" + digits
        }
        return "+1" + digits
    }
}
