package com.schedulersystems.scheduler.services

import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.auth.PhoneAuthCredential
import com.google.firebase.auth.PhoneAuthProvider
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.functions.FirebaseFunctions
import com.google.firebase.storage.FirebaseStorage
import com.google.firebase.messaging.FirebaseMessaging
import com.google.firebase.analytics.FirebaseAnalytics
import com.google.firebase.remoteconfig.FirebaseRemoteConfig
import kotlinx.coroutines.tasks.await
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class FirebaseService @Inject constructor(
    private val auth: FirebaseAuth,
    private val firestore: FirebaseFirestore,
    private val functions: FirebaseFunctions,
    private val storage: FirebaseStorage,
    private val messaging: FirebaseMessaging,
    private val analytics: FirebaseAnalytics,
    private val remoteConfig: FirebaseRemoteConfig
) {
    val currentUserId: String?
        get() = auth.currentUser?.uid

    val isUserSignedIn: Boolean
        get() = auth.currentUser != null

    suspend fun getAuthToken(): String? {
        return auth.currentUser?.getIdToken(false)?.await()?.token
    }

    fun logEvent(eventName: String, params: Map<String, Any> = emptyMap()) {
        analytics.logEvent(eventName, params.toBundle())
    }

    private fun Map<String, Any>.toBundle() = android.os.Bundle().apply {
        forEach { (key, value) ->
            when (value) {
                is String -> putString(key, value)
                is Int -> putInt(key, value)
                is Long -> putLong(key, value)
                is Double -> putDouble(key, value)
                is Boolean -> putBoolean(key, value)
            }
        }
    }
}
