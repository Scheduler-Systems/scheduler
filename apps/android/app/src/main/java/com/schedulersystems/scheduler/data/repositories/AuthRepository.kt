package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.models.domain.User
import kotlinx.coroutines.flow.Flow

interface AuthRepository {
    val currentUser: Flow<User?>
    val isAuthenticated: Flow<Boolean>
    
    suspend fun signInWithPhone(phoneNumber: String): Result<String>
    suspend fun verifyPhoneCode(verificationId: String, code: String): Result<User>
    suspend fun signInWithEmail(email: String, password: String): Result<User>
    suspend fun signUpWithEmail(email: String, password: String): Result<User>
    suspend fun signInWithGoogle(idToken: String): Result<User>
    suspend fun signInWithApple(identityToken: String): Result<User>
    suspend fun signOut(): Result<Unit>
    suspend fun sendPasswordResetEmail(email: String): Result<Unit>
    suspend fun updateUserProfile(displayName: String): Result<Unit>
}
