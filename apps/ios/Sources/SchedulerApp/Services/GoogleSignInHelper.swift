import Foundation

#if canImport(UIKit)
import GoogleSignIn
import UIKit

enum GoogleSignInHelper {
    @MainActor
    static func signIn(presenting viewController: UIViewController) async throws -> GIDSignInResult {
        // GoogleSignIn 8.x: signIn(withPresenting:) returns a non-optional
        // GIDSignInResult and throws on failure (the older API returned an
        // optional, which the migration was still binding with `guard let`).
        return try await GIDSignIn.sharedInstance.signIn(withPresenting: viewController)
    }
    
    static func signOut() {
        GIDSignIn.sharedInstance.signOut()
    }
    
    static func isSignedIn() -> Bool {
        GIDSignIn.sharedInstance.currentUser != nil
    }
    
    static func restorePreviousSignIn() async -> Bool {
        await withCheckedContinuation { continuation in
            GIDSignIn.sharedInstance.restorePreviousSignIn { user, error in
                continuation.resume(returning: user != nil)
            }
        }
    }
}
#else
enum GoogleSignInHelper {
    static func signIn(presenting viewController: Any) async throws -> Any {
        throw AuthError.googleSignInFailed
    }
    
    static func signOut() {}
    
    static func isSignedIn() -> Bool { false }
    
    static func restorePreviousSignIn() async -> Bool { false }
}
#endif
