package com.schedulersystems.scheduler.di

import com.schedulersystems.scheduler.data.repositories.AuthRepository
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.User
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf

class FakeAuthRepository : AuthRepository {

    var signInResult: Result<User> = Result.success(
        User("test-id", "test@example.com", null, "Test User", Role.EMPLOYEE, false, null)
    )
    var signUpResult: Result<User> = Result.success(
        User("test-id", "test@example.com", null, "Test User", Role.EMPLOYEE, false, null)
    )
    var signOutResult: Result<Unit> = Result.success(Unit)
    var resetPasswordResult: Result<Unit> = Result.success(Unit)
    var updateProfileResult: Result<Unit> = Result.success(Unit)
    var phoneSignInResult: Result<String> = Result.success("verification-id-123")
    var verifyPhoneResult: Result<User> = Result.success(
        User("test-id", null, "+1234567890", null, Role.EMPLOYEE, false, null)
    )
    var googleSignInResult: Result<User> = Result.success(
        User("test-id", "google@example.com", null, "Google User", Role.EMPLOYEE, false, null)
    )
    var appleSignInResult: Result<User> = Result.success(
        User("test-id", "apple@example.com", null, "Apple User", Role.EMPLOYEE, false, null)
    )

    override val currentUser: Flow<User?> = flowOf(
        User("test-id", "test@example.com", null, "Test User", Role.EMPLOYEE, false, null)
    )
    override val isAuthenticated: Flow<Boolean> = flowOf(true)

    override suspend fun signInWithPhone(phoneNumber: String): Result<String> = phoneSignInResult
    override suspend fun verifyPhoneCode(verificationId: String, code: String): Result<User> = verifyPhoneResult
    override suspend fun signInWithEmail(email: String, password: String): Result<User> = signInResult
    override suspend fun signUpWithEmail(email: String, password: String): Result<User> = signUpResult
    override suspend fun signInWithGoogle(idToken: String): Result<User> = googleSignInResult
    override suspend fun signInWithApple(identityToken: String): Result<User> = appleSignInResult
    override suspend fun signOut(): Result<Unit> = signOutResult
    override suspend fun sendPasswordResetEmail(email: String): Result<Unit> = resetPasswordResult
    override suspend fun sendEmailVerification(): Result<Unit> = Result.success(Unit)
    override suspend fun reloadAndCheckEmailVerified(): Result<Boolean> = Result.success(false)
    override suspend fun updateUserProfile(displayName: String): Result<Unit> = updateProfileResult
}

class FakeScheduleRepository : ScheduleRepository {

    var schedules: List<Schedule> = emptyList()
    var createResult: Result<String> = Result.success("new-schedule-id")
    var updateResult: Result<Unit> = Result.success(Unit)
    var deleteResult: Result<Unit> = Result.success(Unit)
    var addEmployeeResult: Result<Unit> = Result.success(Unit)
    var removeEmployeeResult: Result<Unit> = Result.success(Unit)

    override fun getSchedulesForUser(userId: String): Flow<List<Schedule>> = flowOf(schedules)
    override suspend fun getScheduleById(scheduleId: String): Schedule? = schedules.firstOrNull { it.id == scheduleId }
    override suspend fun getEmployees(scheduleId: String): List<Employee> =
        schedules.firstOrNull { it.id == scheduleId }?.employees ?: emptyList()
    override suspend fun createSchedule(schedule: Schedule): Result<String> = createResult
    override suspend fun updateSchedule(schedule: Schedule): Result<Unit> = updateResult
    override suspend fun deleteSchedule(scheduleId: String): Result<Unit> = deleteResult
    override suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit> = addEmployeeResult
    override suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit> = removeEmployeeResult
}
