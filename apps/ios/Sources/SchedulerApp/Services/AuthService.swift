import Foundation
import Combine
import FirebaseAuth
import FirebaseCore

#if canImport(UIKit)
import UIKit
#endif

protocol AuthServiceProtocol {
    var authStatePublisher: AnyPublisher<AuthState, Never> { get }
    var currentUser: AuthUser? { get }
    
    func signInWithEmail(email: String, password: String) async throws
    func createAccountWithEmail(email: String, password: String) async throws
    func signInWithGoogle() async throws
    func signInWithApple() async throws
    func beginPhoneAuth(phoneNumber: String) async throws -> String
    func verifyPhoneCode(verificationID: String, code: String) async throws
    func sendPasswordReset(email: String) async throws
    func signOut() async throws
    func deleteAccount() async throws
    func updateEmail(newEmail: String) async throws
    func updatePassword(newPassword: String) async throws
    func sendEmailVerification() async throws
}

final class AuthService: AuthServiceProtocol {
    static let shared = AuthService()
    
    private let auth = Auth.auth()
    private let authStateSubject = CurrentValueSubject<AuthState, Never>(.unauthenticated)
    private var cancellables = Set<AnyCancellable>()
    
    private init() {
        setupAuthStateListener()
    }
    
    var authStatePublisher: AnyPublisher<AuthState, Never> {
        authStateSubject.eraseToAnyPublisher()
    }
    
    var currentUser: AuthUser? {
        guard let user = auth.currentUser else { return nil }
        return mapFirebaseUser(user)
    }
    
    private func setupAuthStateListener() {
        auth.addStateDidChangeListener { [weak self] _, user in
            guard let self = self else { return }
            if let user = user {
                let authUser = self.mapFirebaseUser(user)
                self.authStateSubject.send(.authenticated(authUser))
            } else {
                self.authStateSubject.send(.unauthenticated)
            }
        }
    }
    
    private func mapFirebaseUser(_ user: FirebaseAuth.User) -> AuthUser {
        let providers = user.providerData.compactMap { provider -> AuthProvider? in
            AuthProvider(rawValue: provider.providerID)
        }
        
        return AuthUser(
            id: user.uid,
            email: user.email,
            displayName: user.displayName,
            photoURL: user.photoURL?.absoluteString,
            phoneNumber: user.phoneNumber,
            isEmailVerified: user.isEmailVerified,
            providers: providers
        )
    }
    
    func signInWithEmail(email: String, password: String) async throws {
        authStateSubject.send(.authenticating)
        do {
            _ = try await auth.signIn(withEmail: email, password: password)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func createAccountWithEmail(email: String, password: String) async throws {
        authStateSubject.send(.authenticating)
        do {
            _ = try await auth.createUser(withEmail: email, password: password)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    #if canImport(UIKit)
    func signInWithGoogle() async throws {
        authStateSubject.send(.authenticating)
        do {
            guard let presentingViewController = await getTopViewController() else {
                throw AuthError.googleSignInFailed
            }
            
            let result = try await GoogleSignInHelper.signIn(presenting: presentingViewController)
            guard let idToken = result.user.idToken?.tokenString else {
                throw AuthError.googleSignInFailed
            }
            
            let credential = GoogleAuthProvider.credential(
                withIDToken: idToken,
                accessToken: result.user.accessToken.tokenString
            )
            
            _ = try await auth.signIn(with: credential)
        } catch let error as AuthError {
            throw error
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func signInWithApple() async throws {
        authStateSubject.send(.authenticating)
        do {
            let result = try await AppleSignInHelper.signIn()
            guard let identityToken = result.identityToken else {
                throw AuthError.appleSignInFailed
            }
            
            let nonce = AppleSignInHelper.randomNonceString()
            let credential = OAuthProvider.appleCredential(
                withIDToken: String(data: identityToken, encoding: .utf8) ?? "",
                rawNonce: nonce,
                fullName: result.fullName
            )
            
            _ = try await auth.signIn(with: credential)
        } catch let error as AuthError {
            throw error
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func beginPhoneAuth(phoneNumber: String) async throws -> String {
        authStateSubject.send(.authenticating)
        var verificationID: String?
        var verificationError: Error?
        
        await withCheckedContinuation { continuation in
            PhoneAuthProvider.provider().verifyPhoneNumber(
                phoneNumber,
                uiDelegate: nil
            ) { id, error in
                verificationID = id
                verificationError = error
                continuation.resume()
            }
        }
        
        if let error = verificationError {
            throw mapFirebaseError(error)
        }
        
        guard let id = verificationID else {
            throw AuthError.phoneAuthFailed("Failed to get verification ID")
        }
        
        return id
    }
    
    func verifyPhoneCode(verificationID: String, code: String) async throws {
        authStateSubject.send(.authenticating)
        let credential = PhoneAuthProvider.provider().credential(
            withVerificationID: verificationID,
            verificationCode: code
        )
        
        do {
            _ = try await auth.signIn(with: credential)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    #else
    func signInWithGoogle() async throws {
        throw AuthError.googleSignInFailed
    }
    
    func signInWithApple() async throws {
        throw AuthError.appleSignInFailed
    }
    
    func beginPhoneAuth(phoneNumber: String) async throws -> String {
        throw AuthError.phoneAuthFailed("Phone auth not available on this platform")
    }
    
    func verifyPhoneCode(verificationID: String, code: String) async throws {
        throw AuthError.phoneAuthFailed("Phone auth not available on this platform")
    }
    #endif
    
    func sendPasswordReset(email: String) async throws {
        do {
            try await auth.sendPasswordReset(withEmail: email)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func signOut() async throws {
        do {
            try auth.signOut()
            GoogleSignInHelper.signOut()
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func deleteAccount() async throws {
        guard let user = auth.currentUser else {
            throw AuthError.userNotFound
        }
        
        do {
            try await user.delete()
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func updateEmail(newEmail: String) async throws {
        guard let user = auth.currentUser else {
            throw AuthError.userNotFound
        }
        
        do {
            try await user.sendEmailVerification(beforeUpdatingEmail: newEmail)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func updatePassword(newPassword: String) async throws {
        guard let user = auth.currentUser else {
            throw AuthError.userNotFound
        }
        
        do {
            try await user.updatePassword(to: newPassword)
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    func sendEmailVerification() async throws {
        guard let user = auth.currentUser else {
            throw AuthError.userNotFound
        }
        
        do {
            try await user.sendEmailVerification()
        } catch {
            throw mapFirebaseError(error)
        }
    }
    
    private func mapFirebaseError(_ error: Error) -> AuthError {
        guard let errorCode = AuthErrorCode(rawValue: (error as NSError).code) else {
            return .serverError(error.localizedDescription)
        }
        
        switch errorCode {
        case .invalidEmail:
            return .invalidEmail
        case .wrongPassword:
            return .wrongPassword
        case .userNotFound:
            return .userNotFound
        case .emailAlreadyInUse:
            return .emailAlreadyInUse
        case .weakPassword:
            return .weakPassword
        case .tooManyRequests:
            return .tooManyRequests
        case .networkError:
            return .networkError
        case .invalidCredential:
            return .invalidCredential
        case .invalidVerificationCode:
            return .invalidVerificationCode
        case .requiresRecentLogin:
            return .requiresRecentLogin
        default:
            return .serverError(error.localizedDescription)
        }
    }
    
    #if canImport(UIKit)
    @MainActor
    private func getTopViewController() -> UIViewController? {
        guard let windowScene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = windowScene.windows.first else {
            return nil
        }
        
        var topController = window.rootViewController
        while let presentedViewController = topController?.presentedViewController {
            topController = presentedViewController
        }
        
        return topController
    }
    #endif
}
