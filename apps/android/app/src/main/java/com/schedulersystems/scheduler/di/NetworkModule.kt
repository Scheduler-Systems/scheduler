package com.schedulersystems.scheduler.di

import com.google.firebase.auth.FirebaseAuth
import com.schedulersystems.scheduler.BuildConfig
import com.schedulersystems.scheduler.data.network.SchedulerApi
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Named
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    @Named("api_base_url")
    fun provideBaseUrl(): String {
        return BuildConfig.SCHEDULER_API_URL.ifEmpty {
            "https://api.scheduler-systems.com"
        }
    }

    @Provides
    @Singleton
    fun provideSchedulerApi(
        firebaseAuth: FirebaseAuth,
        @Named("api_base_url") baseUrl: String
    ): SchedulerApi {
        return SchedulerApi(firebaseAuth, baseUrl)
    }
}
