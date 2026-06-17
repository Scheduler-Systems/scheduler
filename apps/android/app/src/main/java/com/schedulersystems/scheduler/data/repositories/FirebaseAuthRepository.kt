package com.schedulersystems.scheduler.data.repositories

import com.google.firebase.auth.AuthCredential
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.FirebaseAuthException
import com.google.firebase.FirebaseException
import com.google.firebase.auth.GoogleAuthProvider
import com.google.firebase.auth.PhoneAuthCredential
import com.google.firebase.auth.PhoneAuthOptions
import com.google.firebase.auth.PhoneAuthProvider
import com.schedulersystems.scheduler.models.domain.User
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import java.util.concurrent.TimeUnit
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class FirebaseAuthRepository @Inject constructor(
    private val firebaseAuth: FirebaseAuth
) : AuthRepository {

    private var storedVerificationId: String? = null
    private var forceResendingToken: PhoneAuthProvider.ForceResendingToken? = null

    override val currentUser: Flow<User?> = callbackFlow {
        val listener = FirebaseAuth.AuthStateListener { auth ->
            val user = auth.currentUser?.toDomainUser()
            trySend(user)
        }
        firebaseAuth.addAuthStateListener(listener)
        awaitClose { firebaseAuth.removeAuthStateListener(listener) }
    }

    override val isAuthenticated: Flow<Boolean> = callbackFlow {
        val listener = FirebaseAuth.AuthStateListener { auth ->
            trySend(auth.currentUser != null)
        }
        firebaseAuth.addAuthStateListener(listener)
        awaitClose { firebaseAuth.removeAuthStateListener(listener) }
    }

    override suspend fun signInWithPhone(phoneNumber: String): Result<String> {
        return try {
            val result = kotlinx.coroutines.suspendCancellableCoroutine<String> { continuation ->
                val options = PhoneAuthOptions.newBuilder(firebaseAuth)
                    .setPhoneNumber(phoneNumber)
                    .setTimeout(60L, TimeUnit.SECONDS)
                    .setCallbacks(object : PhoneAuthProvider.OnVerificationStateChangedCallbacks() {
                        override fun onVerificationCompleted(credential: PhoneAuthCredential) {
                        }

                        override fun onVerificationFailed(e: FirebaseException) {
                            continuation.resumeWith(Result.failure(e))
                        }

                        override fun onCodeSent(
                            verificationId: String,
                            token: PhoneAuthProvider.ForceResendingToken
                        ) {
                            storedVerificationId = verificationId
                            forceResendingToken = token
                            continuation.resumeWith(Result.success(verificationId))
                        }
                    })
                    .build()
                PhoneAuthProvider.verifyPhoneNumber(options)
            }
            Result.success(result)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun verifyPhoneCode(verificationId: String, code: String): Result<User> {
        return try {
            val credential = PhoneAuthProvider.getCredential(verificationId, code)
            val authResult = firebaseAuth.signInWithCredential(credential).await()
            Result.success(authResult.user?.toDomainUser()!!)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun signInWithEmail(email: String, password: String): Result<User> {
        return try {
            val authResult = firebaseAuth.signInWithEmailAndPassword(email, password).await()
            Result.success(authResult.user?.toDomainUser()!!)
        } catch (e: FirebaseAuthException) {
            Result.failure(mapFirebaseException(e))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun signUpWithEmail(email: String, password: String): Result<User> {
        return try {
            val authResult = firebaseAuth.createUserWithEmailAndPassword(email, password).await()
            Result.success(authResult.user?.toDomainUser()!!)
        } catch (e: FirebaseAuthException) {
            Result.failure(mapFirebaseException(e))
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun signInWithGoogle(idToken: String): Result<User> {
        return try {
            val credential = GoogleAuthProvider.getCredential(idToken, null)
            val authResult = firebaseAuth.signInWithCredential(credential).await()
            Result.success(authResult.user?.toDomainUser()!!)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun signInWithApple(identityToken: String): Result<User> {
        return try {
            val credential = getAppleCredential(identityToken)
            val authResult = firebaseAuth.signInWithCredential(credential).await()
            Result.success(authResult.user?.toDomainUser()!!)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun signOut(): Result<Unit> {
        return try {
            firebaseAuth.signOut()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun sendPasswordResetEmail(email: String): Result<Unit> {
        return try {
            firebaseAuth.sendPasswordResetEmail(email).await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun updateUserProfile(displayName: String): Result<Unit> {
        return try {
            val user = firebaseAuth.currentUser
            val profileUpdates = com.google.firebase.auth.UserProfileChangeRequest.Builder()
                .setDisplayName(displayName)
                .build()
            user?.updateProfile(profileUpdates)?.await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun getAppleCredential(identityToken: String): AuthCredential {
        return com.google.firebase.auth.OAuthProvider.newCredentialBuilder("apple.com")
            .setIdTokenWithRawNonce(identityToken, null)
            .build()
    }

    private fun com.google.firebase.auth.FirebaseUser.toDomainUser(): User {
        return User(
            id = uid,
            email = email,
            phone = phoneNumber,
            displayName = displayName,
            role = null,
            isPremium = false,
            tenantId = null
        )
    }

    private fun mapFirebaseException(e: FirebaseAuthException): Exception {
        return when (e.errorCode) {
            "ERROR_INVALID_EMAIL", "ERROR_USER_NOT_FOUND", "ERROR_WRONG_PASSWORD" ->
                AuthException.InvalidCredentials()
            "ERROR_EMAIL_ALREADY_IN_USE" ->
                AuthException.EmailAlreadyInUse()
            "ERROR_WEAK_PASSWORD" ->
                AuthException.WeakPassword()
            "ERROR_TOO_MANY_REQUESTS" ->
                AuthException.TooManyRequests()
            else -> e
        }
    }
}

sealed class AuthException : Exception() {
    class InvalidCredentials : AuthException() {
        override val message: String = "Invalid email or password"
    }
    class EmailAlreadyInUse : AuthException() {
        override val message: String = "Email is already registered"
    }
    class WeakPassword : AuthException() {
        override val message: String = "Password is too weak"
    }
    class TooManyRequests : AuthException() {
        override val message: String = "Too many attempts. Please try again later"
    }
    class UserCancelled : AuthException() {
        override val message: String = "Sign in was cancelled"
    }
}
