package com.schedulersystems.scheduler.data.network

import com.google.firebase.auth.FirebaseAuth
import com.schedulersystems.scheduler.data.network.dto.AddEmployeeApiRequest
import com.schedulersystems.scheduler.data.network.dto.ApiEmployeeDto
import com.schedulersystems.scheduler.data.network.dto.EmployeeListApiResponse
import com.schedulersystems.scheduler.data.network.dto.InvitationListResponse
import com.schedulersystems.scheduler.data.network.dto.ScheduleDto
import com.schedulersystems.scheduler.data.network.dto.ScheduleListResponse
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

interface SchedulerApiService {
    @GET("v1/tenants/{tid}/schedules")
    suspend fun listSchedules(
        @Path("tid") tenantId: String,
        @Query("user_id") userId: String
    ): retrofit2.Response<ScheduleListResponse>

    @POST("v1/tenants/{tid}/schedules")
    suspend fun createSchedule(
        @Path("tid") tenantId: String,
        @Body schedule: ScheduleDto
    ): retrofit2.Response<ScheduleDto>

    @GET("v1/tenants/{tid}/schedules/{id}")
    suspend fun getSchedule(
        @Path("tid") tenantId: String,
        @Path("id") scheduleId: String
    ): retrofit2.Response<ScheduleDto>

    @PUT("v1/tenants/{tid}/schedules/{id}")
    suspend fun updateSchedule(
        @Path("tid") tenantId: String,
        @Path("id") scheduleId: String,
        @Body schedule: ScheduleDto
    ): retrofit2.Response<ScheduleDto>

    @DELETE("v1/tenants/{tid}/schedules/{id}")
    suspend fun deleteSchedule(
        @Path("tid") tenantId: String,
        @Path("id") scheduleId: String
    ): retrofit2.Response<Unit>

    // Schedule roster (separate endpoint; employees are NOT embedded in the schedule).
    @GET("v1/tenants/{tid}/schedules/{sid}/employees")
    suspend fun listEmployees(
        @Path("tid") tenantId: String,
        @Path("sid") scheduleId: String
    ): retrofit2.Response<EmployeeListApiResponse>

    @POST("v1/tenants/{tid}/schedules/{sid}/employees")
    suspend fun addEmployee(
        @Path("tid") tenantId: String,
        @Path("sid") scheduleId: String,
        @Body employee: AddEmployeeApiRequest
    ): retrofit2.Response<ApiEmployeeDto>

    // Identity is the (url-encoded) employee email.
    @DELETE("v1/tenants/{tid}/schedules/{sid}/employees/{email}")
    suspend fun removeEmployee(
        @Path("tid") tenantId: String,
        @Path("sid") scheduleId: String,
        @Path("email") employeeEmail: String
    ): retrofit2.Response<Unit>

    @GET("v1/tenants/{tid}/schedules/{sid}/employees/invitations")
    suspend fun listInvitations(
        @Path("tid") tenantId: String,
        @Path("sid") scheduleId: String
    ): retrofit2.Response<InvitationListResponse>
}

class AuthInterceptor(private val firebaseAuth: FirebaseAuth) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val token = try {
            val task = firebaseAuth.currentUser?.getIdToken(false)
            if (task != null) {
                val result = com.google.android.gms.tasks.Tasks.await(task)
                result.token
            } else null
        } catch (_: Exception) {
            null
        }
        val user = firebaseAuth.currentUser
        val request = chain.request().newBuilder().apply {
            token?.let { addHeader("Authorization", "Bearer $it") }
            user?.let {
                addHeader("x-user-id", it.uid)
            }
            // Required by the API (tracing; 400 missing_actor_context without it).
            addHeader("x-correlation-id", java.util.UUID.randomUUID().toString())
        }.build()
        return chain.proceed(request)
    }
}

@Singleton
class SchedulerApi(
    firebaseAuth: FirebaseAuth,
    baseUrl: String
) {
    val service: SchedulerApiService

    init {
        val client = OkHttpClient.Builder()
            .addInterceptor(AuthInterceptor(firebaseAuth))
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()

        val retrofit = Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        service = retrofit.create(SchedulerApiService::class.java)
    }
}
