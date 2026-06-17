import Foundation

struct AuthUser: Identifiable {
    let id: String
    let email: String?
    let displayName: String?
    let photoURL: String?
    let phoneNumber: String?
    let isEmailVerified: Bool
    let providers: [AuthProvider]
    
    var isLoggedIn: Bool { !id.isEmpty }
}

enum AuthProvider: String, CaseIterable {
    case email = "password"
    case google = "google.com"
    case apple = "apple.com"
    case phone = "phone"
    case anonymous = "anonymous"
    
    var displayName: String {
        switch self {
        case .email: return "Email"
        case .google: return "Google"
        case .apple: return "Apple"
        case .phone: return "Phone"
        case .anonymous: return "Anonymous"
        }
    }
}

enum AuthState {
    case unauthenticated
    case authenticating
    case authenticated(AuthUser)
    case error(String)
    
    var isAuthenticated: Bool {
        if case .authenticated = self { return true }
        return false
    }
    
    var user: AuthUser? {
        if case .authenticated(let user) = self { return user }
        return nil
    }
    
    var isLoading: Bool {
        if case .authenticating = self { return true }
        return false
    }
}

enum AuthError: LocalizedError {
    case invalidEmail
    case wrongPassword
    case userNotFound
    case emailAlreadyInUse
    case weakPassword
    case tooManyRequests
    case networkError
    case userCancelled
    case invalidCredential
    case invalidVerificationCode
    case phoneAuthFailed(String)
    case appleSignInFailed
    case googleSignInFailed
    case serverError(String)
    case requiresRecentLogin
    
    var errorDescription: String? {
        switch self {
        case .invalidEmail: return "Invalid email address"
        case .wrongPassword: return "Incorrect password"
        case .userNotFound: return "No account found with this email"
        case .emailAlreadyInUse: return "Email is already registered"
        case .weakPassword: return "Password is too weak"
        case .tooManyRequests: return "Too many attempts. Please try again later"
        case .networkError: return "Network error. Please check your connection"
        case .userCancelled: return "Sign in was cancelled"
        case .invalidCredential: return "Invalid credentials"
        case .invalidVerificationCode: return "Invalid verification code"
        case .phoneAuthFailed(let message): return message
        case .appleSignInFailed: return "Apple Sign In failed"
        case .googleSignInFailed: return "Google Sign In failed"
        case .serverError(let message): return message
        case .requiresRecentLogin: return "Please sign in again to perform this action"
        }
    }
}

struct PhoneAuthState {
    var verificationID: String?
    var isCodeSent: Bool = false
    var phoneNumber: String = ""
    var error: AuthError?
}

enum PasswordResetState: Equatable {
    case idle
    case sending
    case sent
    case error(String)
}
