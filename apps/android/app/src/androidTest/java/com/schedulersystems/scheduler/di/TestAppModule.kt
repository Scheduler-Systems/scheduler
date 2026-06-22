package com.schedulersystems.scheduler.di

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.Shift
import com.schedulersystems.scheduler.models.domain.ShiftRow
import com.schedulersystems.scheduler.models.domain.User
import dagger.Module
import dagger.Provides
import dagger.hilt.components.SingletonComponent
import dagger.hilt.testing.TestInstallIn
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import java.time.Instant
import java.time.LocalTime
import javax.inject.Singleton

class TestFakeAuthRepository : AuthRepository {

    var signInResult: Result<User> = Result.success(
        User("test-id", "test@example.com", null, "Test User", Role.EMPLOYEE, false, null)
    )

    override val currentUser: Flow<User?> = flowOf(
        User("test-id", "test@example.com", null, "Test User", Role.EMPLOYEE, false, null)
    )
    override val isAuthenticated: Flow<Boolean> = flowOf(true)

    override suspend fun signInWithPhone(phoneNumber: String): Result<String> = Result.success("verification-id")
    override suspend fun verifyPhoneCode(verificationId: String, code: String): Result<User> = Result.success(
        User("test-id", null, "+1234567890", null, Role.EMPLOYEE, false, null)
    )
    override suspend fun signInWithEmail(email: String, password: String): Result<User> = signInResult
    override suspend fun signUpWithEmail(email: String, password: String): Result<User> = signInResult
    override suspend fun signInWithGoogle(idToken: String): Result<User> = signInResult
    override suspend fun signInWithApple(identityToken: String): Result<User> = signInResult
    override suspend fun signOut(): Result<Unit> = Result.success(Unit)
    override suspend fun sendPasswordResetEmail(email: String): Result<Unit> = Result.success(Unit)
    override suspend fun sendEmailVerification(): Result<Unit> = Result.success(Unit)
    override suspend fun reloadAndCheckEmailVerified(): Result<Boolean> = Result.success(false)
    override suspend fun updateUserProfile(displayName: String): Result<Unit> = Result.success(Unit)
}

class TestFakeScheduleRepository : ScheduleRepository {

    var schedules: List<Schedule> = listOf(
        Schedule(
            id = "sched-1",
            name = "Test Schedule",
            tenantId = "tenant-1",
            employees = listOf(
                Employee("emp-1", "Test Employee", "emp@example.com", null, Role.EMPLOYEE, emptyMap())
            ),
            currentPriorities = listOf("priority-1"),
            settings = ScheduleSettings(
                submissionDeadline = null,
                enabledShifts = EnabledShifts(mornings = true, afternoons = true, evenings = false),
                timezone = "UTC"
            ),
            nextSchedule = listOf(
                ShiftRow(
                    shifts = listOf(
                        Shift("Mon", LocalTime.of(7, 0), LocalTime.of(13, 0), null),
                        Shift("Mon", LocalTime.of(14, 0), LocalTime.of(20, 0), null)
                    )
                )
            ),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
    )

    override fun getSchedulesForUser(userId: String): Flow<List<Schedule>> = flowOf(schedules)
    override suspend fun getScheduleById(scheduleId: String): Schedule? = schedules.firstOrNull { it.id == scheduleId }
    override suspend fun getEmployees(scheduleId: String): List<com.schedulersystems.scheduler.models.domain.Employee> =
        schedules.firstOrNull { it.id == scheduleId }?.employees ?: emptyList()
    override suspend fun getInvitations(scheduleId: String): List<com.schedulersystems.scheduler.models.domain.ScheduleRequest> = emptyList()
    override suspend fun createSchedule(schedule: Schedule): Result<String> = Result.success("new-id")
    override suspend fun updateSchedule(schedule: Schedule): Result<Unit> = Result.success(Unit)
    override suspend fun deleteSchedule(scheduleId: String): Result<Unit> = Result.success(Unit)
    override suspend fun addEmployee(scheduleId: String, employee: com.schedulersystems.scheduler.models.domain.Employee): Result<Unit> = Result.success(Unit)
    override suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit> = Result.success(Unit)
    override suspend fun submitAvailability(scheduleId: String, availability: Map<String, Any>): Result<Unit> = Result.success(Unit)
}

@TestInstallIn(
    components = [SingletonComponent::class],
    replaces = [AppModule::class]
)
@Module
object TestAppModule {

    @Provides
    @Singleton
    fun provideAuthRepository(): AuthRepository = TestFakeAuthRepository()

    @Provides
    @Singleton
    fun provideScheduleRepository(): ScheduleRepository = TestFakeScheduleRepository()
}
