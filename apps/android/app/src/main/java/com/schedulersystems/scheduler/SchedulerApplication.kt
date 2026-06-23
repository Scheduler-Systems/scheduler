package com.schedulersystems.scheduler

import android.app.Application
import com.google.firebase.firestore.FirebaseFirestore
import dagger.hilt.android.HiltAndroidApp

@HiltAndroidApp
class SchedulerApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        // Route Firestore to the isolated chat emulator on :8089 EAGERLY, before any Firestore use.
        // The chat screens call FirebaseFirestore.getInstance() directly (not the lazy Hilt
        // provider), so the emulator must be wired here at app startup or those screens would hit
        // production Firestore. useEmulator() only overrides host:port — the project id stays the
        // bundled one (scheduler-ci-placeholder), which the seed must match. 8089 (NOT 8088 = the
        // user's GAL emulator). This is the single useEmulator call for the process singleton
        // (the Hilt provider no longer calls it).
        if (BuildConfig.USE_FIREBASE_EMULATOR) {
            FirebaseFirestore.getInstance().useEmulator(BuildConfig.FIREBASE_EMULATOR_HOST, 8089)
        }
    }
}
