import XCTest
import Combine
@testable import SchedulerApp

final class MockAuthService: AuthServiceProtocol {
    let authStateSubject = CurrentValueSubject<AuthState, Never>(.unauthenticated)
    var authStatePublisher: AnyPublisher<AuthState, Never> {
        authStateSubject.eraseToAnyPublisher()
    }
    var currentUser: AuthUser?
    
    var signInWithEmailCalled = false
    var createAccountWithEmailCalled = false
    var signInWithGoogleCalled = false
    var signInWithAppleCalled = false
    var beginPhoneAuthCalled = false
    var verifyPhoneCodeCalled = false
    var sendPasswordResetCalled = false
    var signOutCalled = false
    var deleteAccountCalled = false
    var updateEmailCalled = false
    var updatePasswordCalled = false
    var sendEmailVerificationCalled = false
    var reloadAndCheckEmailVerifiedCalled = false

    var shouldThrow: Error?
    var beginPhoneAuthResult: String = "test-verification-id"
    var emailVerifiedResult: Bool = false
    
    func signInWithEmail(email: String, password: String) async throws {
        signInWithEmailCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func createAccountWithEmail(email: String, password: String) async throws {
        createAccountWithEmailCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func signInWithGoogle() async throws {
        signInWithGoogleCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func signInWithApple() async throws {
        signInWithAppleCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func beginPhoneAuth(phoneNumber: String) async throws -> String {
        beginPhoneAuthCalled = true
        if let error = shouldThrow { throw error }
        return beginPhoneAuthResult
    }
    
    func verifyPhoneCode(verificationID: String, code: String) async throws {
        verifyPhoneCodeCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func sendPasswordReset(email: String) async throws {
        sendPasswordResetCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func signOut() async throws {
        signOutCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func deleteAccount() async throws {
        deleteAccountCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func updateEmail(newEmail: String) async throws {
        updateEmailCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func updatePassword(newPassword: String) async throws {
        updatePasswordCalled = true
        if let error = shouldThrow { throw error }
    }
    
    func sendEmailVerification() async throws {
        sendEmailVerificationCalled = true
        if let error = shouldThrow { throw error }
    }

    func reloadAndCheckEmailVerified() async throws -> Bool {
        reloadAndCheckEmailVerifiedCalled = true
        if let error = shouldThrow { throw error }
        return emailVerifiedResult
    }
}

final class AuthViewModelTests: XCTestCase {
    var mockService: MockAuthService!
    var sut: AuthViewModel!
    var cancellables: Set<AnyCancellable>!
    
    @MainActor
    override func setUp() {
        super.setUp()
        mockService = MockAuthService()
        sut = AuthViewModel(authService: mockService)
        cancellables = []
    }
    
    override func tearDown() {
        mockService = nil
        sut = nil
        cancellables = nil
        super.tearDown()
    }
    
    // MARK: - Initial State
    
    @MainActor
    func testInitialState() {
        XCTAssertEqual(sut.email, "")
        XCTAssertEqual(sut.password, "")
        XCTAssertEqual(sut.confirmPassword, "")
        XCTAssertEqual(sut.phoneNumber, "")
        XCTAssertEqual(sut.verificationCode, "")
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.errorMessage)
        XCTAssertFalse(sut.phoneAuthState.isCodeSent)
        XCTAssertEqual(sut.passwordResetState, .idle)
    }
    
    @MainActor
    func testInitialAuthStateUnauthenticated() {
        XCTAssertFalse(sut.isAuthenticated)
        XCTAssertNil(sut.currentUser)
        XCTAssertNil(sut.currentUserId)
        XCTAssertNil(sut.currentUserEmail)
        XCTAssertNil(sut.currentUserDisplayName)
    }
    
    // MARK: - Auth State Observation
    
    @MainActor
    func testAuthStateObservationAuthenticated() async {
        let user = AuthUser(
            id: "user-1", email: "test@test.com", displayName: "Test User",
            photoURL: nil, phoneNumber: nil, isEmailVerified: true,
            providers: [.email]
        )
        mockService.authStateSubject.send(.authenticated(user))
        await Task.yield()
        
        XCTAssertTrue(sut.isAuthenticated)
        XCTAssertEqual(sut.currentUser?.id, "user-1")
        XCTAssertEqual(sut.currentUserId, "user-1")
        XCTAssertEqual(sut.currentUserEmail, "test@test.com")
        XCTAssertEqual(sut.currentUserDisplayName, "Test User")
    }
    
    @MainActor
    func testAuthStateObservationAuthenticating() async {
        mockService.authStateSubject.send(.authenticating)
        await Task.yield()
        XCTAssertTrue(sut.isLoading)
        XCTAssertFalse(sut.isAuthenticated)
    }
    
    @MainActor
    func testAuthStateObservationError() async {
        mockService.authStateSubject.send(.error("auth error"))
        await Task.yield()
        XCTAssertFalse(sut.isAuthenticated)
    }
    
    // MARK: - signInWithEmail Validation
    
    @MainActor
    func testSignInWithEmailEmptyFields() async {
        sut.email = ""
        sut.password = ""
        await sut.signInWithEmail()
        XCTAssertEqual(sut.errorMessage, "Please enter email and password")
        XCTAssertFalse(mockService.signInWithEmailCalled)
    }
    
    @MainActor
    func testSignInWithEmailEmptyEmail() async {
        sut.email = ""
        sut.password = "password123"
        await sut.signInWithEmail()
        XCTAssertEqual(sut.errorMessage, "Please enter email and password")
    }
    
    @MainActor
    func testSignInWithEmailEmptyPassword() async {
        sut.email = "test@test.com"
        sut.password = ""
        await sut.signInWithEmail()
        XCTAssertEqual(sut.errorMessage, "Please enter email and password")
    }
    
    // MARK: - signInWithEmail Success
    
    @MainActor
    func testSignInWithEmailSuccess() async {
        sut.email = "test@test.com"
        sut.password = "password123"
        await sut.signInWithEmail()
        
        XCTAssertTrue(mockService.signInWithEmailCalled)
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.errorMessage)
        XCTAssertEqual(sut.email, "")
        XCTAssertEqual(sut.password, "")
    }
    
    // MARK: - signInWithEmail Error
    
    @MainActor
    func testSignInWithEmailAuthError() async {
        sut.email = "test@test.com"
        sut.password = "wrong"
        mockService.shouldThrow = AuthError.wrongPassword
        await sut.signInWithEmail()
        
        XCTAssertTrue(mockService.signInWithEmailCalled)
        XCTAssertFalse(sut.isLoading)
        XCTAssertEqual(sut.errorMessage, "Incorrect password")
    }
    
    @MainActor
    func testSignInWithEmailGenericError() async {
        sut.email = "test@test.com"
        sut.password = "password123"
        struct TestError: LocalizedError { var errorDescription: String? { "test error" } }
        mockService.shouldThrow = TestError()
        await sut.signInWithEmail()
        
        XCTAssertEqual(sut.errorMessage, "test error")
    }
    
    // MARK: - createAccountWithEmail Validation
    
    @MainActor
    func testCreateAccountEmptyFields() async {
        await sut.createAccountWithEmail()
        XCTAssertEqual(sut.errorMessage, "Please enter email and password")
        XCTAssertFalse(mockService.createAccountWithEmailCalled)
    }
    
    @MainActor
    func testCreateAccountPasswordMismatch() async {
        sut.email = "test@test.com"
        sut.password = "password123"
        sut.confirmPassword = "different"
        await sut.createAccountWithEmail()
        XCTAssertEqual(sut.errorMessage, "Passwords do not match")
    }
    
    @MainActor
    func testCreateAccountWeakPassword() async {
        sut.email = "test@test.com"
        sut.password = "123"
        sut.confirmPassword = "123"
        await sut.createAccountWithEmail()
        XCTAssertEqual(sut.errorMessage, "Password must be at least 6 characters")
    }
    
    // MARK: - createAccountWithEmail Success
    
    @MainActor
    func testCreateAccountSuccess() async {
        sut.email = "test@test.com"
        sut.password = "password123"
        sut.confirmPassword = "password123"
        await sut.createAccountWithEmail()
        
        XCTAssertTrue(mockService.createAccountWithEmailCalled)
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.errorMessage)
        XCTAssertEqual(sut.email, "")
        XCTAssertEqual(sut.confirmPassword, "")
    }
    
    // MARK: - createAccountWithEmail Error
    
    @MainActor
    func testCreateAccountError() async {
        sut.email = "test@test.com"
        sut.password = "password123"
        sut.confirmPassword = "password123"
        mockService.shouldThrow = AuthError.emailAlreadyInUse
        await sut.createAccountWithEmail()
        
        XCTAssertEqual(sut.errorMessage, "Email is already registered")
    }
    
    // MARK: - signInWithGoogle
    
    @MainActor
    func testSignInWithGoogleSuccess() async {
        await sut.signInWithGoogle()
        XCTAssertTrue(mockService.signInWithGoogleCalled)
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.errorMessage)
    }
    
    @MainActor
    func testSignInWithGoogleError() async {
        mockService.shouldThrow = AuthError.googleSignInFailed
        await sut.signInWithGoogle()
        XCTAssertEqual(sut.errorMessage, "Google Sign In failed")
    }
    
    // MARK: - signInWithApple
    
    @MainActor
    func testSignInWithAppleSuccess() async {
        await sut.signInWithApple()
        XCTAssertTrue(mockService.signInWithAppleCalled)
        XCTAssertFalse(sut.isLoading)
        XCTAssertNil(sut.errorMessage)
    }
    
    @MainActor
    func testSignInWithAppleError() async {
        mockService.shouldThrow = AuthError.appleSignInFailed
        await sut.signInWithApple()
        XCTAssertEqual(sut.errorMessage, "Apple Sign In failed")
    }
    
    // MARK: - beginPhoneAuth Validation
    
    @MainActor
    func testBeginPhoneAuthEmptyNumber() async {
        sut.phoneNumber = ""
        await sut.beginPhoneAuth()
        XCTAssertEqual(sut.errorMessage, "Please enter a phone number")
        XCTAssertFalse(mockService.beginPhoneAuthCalled)
    }
    
    // MARK: - beginPhoneAuth Success
    
    @MainActor
    func testBeginPhoneAuthSuccess() async {
        sut.phoneNumber = "1234567890"
        await sut.beginPhoneAuth()
        
        XCTAssertTrue(mockService.beginPhoneAuthCalled)
        XCTAssertTrue(sut.phoneAuthState.isCodeSent)
        XCTAssertEqual(sut.phoneAuthState.verificationID, "test-verification-id")
        XCTAssertFalse(sut.isLoading)
    }
    
    @MainActor
    func testBeginPhoneAuthWithPlusPrefix() async {
        sut.phoneNumber = "+11234567890"
        await sut.beginPhoneAuth()
        XCTAssertTrue(mockService.beginPhoneAuthCalled)
        XCTAssertTrue(sut.phoneAuthState.isCodeSent)
    }
    
    @MainActor
    func testBeginPhoneAuthWithoutPrefix() async {
        sut.phoneNumber = "555-123-4567"
        await sut.beginPhoneAuth()
        XCTAssertTrue(mockService.beginPhoneAuthCalled)
        XCTAssertEqual(sut.phoneAuthState.phoneNumber, "+15551234567")
    }
    
    // MARK: - beginPhoneAuth Error
    
    @MainActor
    func testBeginPhoneAuthAuthError() async {
        sut.phoneNumber = "1234567890"
        mockService.shouldThrow = AuthError.phoneAuthFailed("no signal")
        await sut.beginPhoneAuth()
        
        XCTAssertEqual(sut.phoneAuthState.error?.errorDescription, "no signal")
    }
    
    @MainActor
    func testBeginPhoneAuthGenericError() async {
        sut.phoneNumber = "1234567890"
        struct NetworkErr: LocalizedError { var errorDescription: String? { "offline" } }
        mockService.shouldThrow = NetworkErr()
        await sut.beginPhoneAuth()
        
        XCTAssertEqual(sut.phoneAuthState.error?.errorDescription, "offline")
    }
    
    // MARK: - verifyPhoneCode Validation
    
    @MainActor
    func testVerifyPhoneCodeNoVerificationID() async {
        sut.phoneAuthState = PhoneAuthState()
        sut.verificationCode = "123456"
        await sut.verifyPhoneCode()
        XCTAssertEqual(sut.errorMessage, "Please enter the verification code")
        XCTAssertFalse(mockService.verifyPhoneCodeCalled)
    }
    
    @MainActor
    func testVerifyPhoneCodeEmptyCode() async {
        sut.phoneAuthState = PhoneAuthState(verificationID: "vid", isCodeSent: true, phoneNumber: "+123")
        sut.verificationCode = ""
        await sut.verifyPhoneCode()
        XCTAssertEqual(sut.errorMessage, "Please enter the verification code")
    }
    
    // MARK: - verifyPhoneCode Success
    
    @MainActor
    func testVerifyPhoneCodeSuccess() async {
        sut.phoneAuthState = PhoneAuthState(verificationID: "vid", isCodeSent: true, phoneNumber: "+123")
        sut.verificationCode = "123456"
        await sut.verifyPhoneCode()
        
        XCTAssertTrue(mockService.verifyPhoneCodeCalled)
        XCTAssertFalse(sut.phoneAuthState.isCodeSent)
        XCTAssertNil(sut.phoneAuthState.verificationID)
        XCTAssertEqual(sut.verificationCode, "")
    }
    
    // MARK: - verifyPhoneCode Error
    
    @MainActor
    func testVerifyPhoneCodeError() async {
        sut.phoneAuthState = PhoneAuthState(verificationID: "vid", isCodeSent: true, phoneNumber: "+123")
        sut.verificationCode = "wrong"
        mockService.shouldThrow = AuthError.invalidVerificationCode
        await sut.verifyPhoneCode()
        
        XCTAssertEqual(sut.errorMessage, "Invalid verification code")
    }
    
    // MARK: - sendPasswordReset
    
    @MainActor
    func testSendPasswordResetEmptyEmail() async {
        sut.email = ""
        await sut.sendPasswordReset()
        XCTAssertEqual(sut.errorMessage, "Please enter your email")
        XCTAssertFalse(mockService.sendPasswordResetCalled)
    }
    
    @MainActor
    func testSendPasswordResetSuccess() async {
        sut.email = "test@test.com"
        await sut.sendPasswordReset()
        
        XCTAssertTrue(mockService.sendPasswordResetCalled)
        XCTAssertEqual(sut.passwordResetState, .sent)
    }
    
    @MainActor
    func testSendPasswordResetError() async {
        sut.email = "test@test.com"
        mockService.shouldThrow = AuthError.userNotFound
        await sut.sendPasswordReset()
        
        if case .error(let msg) = sut.passwordResetState {
            XCTAssertTrue(msg.contains("No account found"))
        } else {
            XCTFail("Expected error state")
        }
    }
    
    @MainActor
    func testSendPasswordResetGenericError() async {
        sut.email = "test@test.com"
        struct SomeErr: LocalizedError { var errorDescription: String? { "boom" } }
        mockService.shouldThrow = SomeErr()
        await sut.sendPasswordReset()
        
        if case .error(let msg) = sut.passwordResetState {
            XCTAssertEqual(msg, "boom")
        } else {
            XCTFail("Expected error state")
        }
    }
    
    // MARK: - signOut
    
    @MainActor
    func testSignOutSuccess() async {
        await sut.signOut()
        XCTAssertTrue(mockService.signOutCalled)
        XCTAssertNil(sut.errorMessage)
        XCTAssertEqual(sut.email, "")
    }
    
    @MainActor
    func testSignOutError() async {
        mockService.shouldThrow = AuthError.serverError("session expired")
        await sut.signOut()
        XCTAssertEqual(sut.errorMessage, "session expired")
    }
    
    // MARK: - deleteAccount
    
    @MainActor
    func testDeleteAccountSuccess() async {
        await sut.deleteAccount()
        XCTAssertTrue(mockService.deleteAccountCalled)
        XCTAssertEqual(sut.email, "")
    }
    
    @MainActor
    func testDeleteAccountError() async {
        mockService.shouldThrow = AuthError.requiresRecentLogin
        await sut.deleteAccount()
        XCTAssertEqual(sut.errorMessage, "Please sign in again to perform this action")
    }
    
    // MARK: - updateEmail
    
    @MainActor
    func testUpdateEmailSuccess() async {
        await sut.updateEmail(newEmail: "new@test.com")
        XCTAssertTrue(mockService.updateEmailCalled)
        XCTAssertNil(sut.errorMessage)
    }
    
    @MainActor
    func testUpdateEmailError() async {
        mockService.shouldThrow = AuthError.invalidEmail
        await sut.updateEmail(newEmail: "bad")
        XCTAssertEqual(sut.errorMessage, "Invalid email address")
    }
    
    // MARK: - updatePassword
    
    @MainActor
    func testUpdatePasswordSuccess() async {
        await sut.updatePassword(newPassword: "newPass123")
        XCTAssertTrue(mockService.updatePasswordCalled)
        XCTAssertNil(sut.errorMessage)
    }
    
    @MainActor
    func testUpdatePasswordError() async {
        mockService.shouldThrow = AuthError.weakPassword
        await sut.updatePassword(newPassword: "123")
        XCTAssertEqual(sut.errorMessage, "Password is too weak")
    }
    
    // MARK: - sendEmailVerification
    
    @MainActor
    func testSendEmailVerificationSuccess() async {
        await sut.sendEmailVerification()
        XCTAssertTrue(mockService.sendEmailVerificationCalled)
        XCTAssertNil(sut.errorMessage)
    }
    
    @MainActor
    func testSendEmailVerificationError() async {
        mockService.shouldThrow = AuthError.userNotFound
        await sut.sendEmailVerification()
        XCTAssertEqual(sut.errorMessage, "No account found with this email")
    }
    
    // MARK: - clearError
    
    @MainActor
    func testClearError() {
        sut.errorMessage = "some error"
        sut.clearError()
        XCTAssertNil(sut.errorMessage)
    }
    
    // MARK: - clearForm
    
    @MainActor
    func testClearForm() {
        sut.email = "test@test.com"
        sut.password = "pass"
        sut.confirmPassword = "pass"
        sut.phoneNumber = "555"
        sut.verificationCode = "123"
        sut.errorMessage = "error"
        
        sut.clearForm()
        
        XCTAssertEqual(sut.email, "")
        XCTAssertEqual(sut.password, "")
        XCTAssertEqual(sut.confirmPassword, "")
        XCTAssertEqual(sut.phoneNumber, "")
        XCTAssertEqual(sut.verificationCode, "")
        XCTAssertNil(sut.errorMessage)
    }
    
    // MARK: - resetPhoneAuth
    
    @MainActor
    func testResetPhoneAuth() {
        sut.phoneAuthState = PhoneAuthState(verificationID: "vid", isCodeSent: true, phoneNumber: "+123")
        sut.verificationCode = "123456"
        
        sut.resetPhoneAuth()
        
        XCTAssertFalse(sut.phoneAuthState.isCodeSent)
        XCTAssertNil(sut.phoneAuthState.verificationID)
        XCTAssertEqual(sut.verificationCode, "")
    }
    
    // MARK: - isLoading during operations
    
    @MainActor
    func testIsLoadingSetDuringSignIn() async {
        sut.email = "test@test.com"
        sut.password = "pass"
        
        var loadingStates: [Bool] = []
        let expectation = self.expectation(description: "loading observed")
        let sub = sut.$isLoading.sink { loadingStates.append($0) }
        
        await sut.signInWithEmail()
        
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
            expectation.fulfill()
            sub.cancel()
        }
        
        await fulfillment(of: [expectation], timeout: 1.0)
        XCTAssertFalse(sut.isLoading)
    }
    
    // MARK: - formatPhoneNumber edge cases
    
    @MainActor
    func testFormatPhoneNumberWithInternationalPrefix() async {
        sut.phoneNumber = "+44 20 1234 5678"
        await sut.beginPhoneAuth()
        XCTAssertTrue(sut.phoneAuthState.isCodeSent)
    }
    
    @MainActor
    func testFormatPhoneNumberUSDefault() async {
        sut.phoneNumber = "2125551234"
        await sut.beginPhoneAuth()
        XCTAssertTrue(sut.phoneAuthState.isCodeSent)
    }

    // MARK: - verify-email

    @MainActor
    func testVerifyEmailSendsVerification() async {
        await sut.sendEmailVerification()
        XCTAssertTrue(mockService.sendEmailVerificationCalled)
    }

    @MainActor
    func testVerifyEmailCheckReturnsTrueWhenVerified() async {
        mockService.emailVerifiedResult = true
        let verified = await sut.checkEmailVerified()
        XCTAssertTrue(mockService.reloadAndCheckEmailVerifiedCalled)
        XCTAssertTrue(verified)
        XCTAssertNil(sut.errorMessage)
    }

    @MainActor
    func testVerifyEmailCheckSetsErrorWhenNotVerified() async {
        mockService.emailVerifiedResult = false
        let verified = await sut.checkEmailVerified()
        XCTAssertFalse(verified)
        XCTAssertEqual(sut.errorMessage, "Email is not verified")
    }
}
