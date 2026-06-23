package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.Employee
import kotlinx.coroutines.flow.Flow

interface ScheduleRepository {
    fun getSchedulesForUser(userId: String): Flow<List<Schedule>>
    suspend fun getScheduleById(scheduleId: String): Schedule?
    suspend fun getEmployees(scheduleId: String): List<Employee>
    suspend fun getInvitations(scheduleId: String): List<com.schedulersystems.scheduler.models.domain.ScheduleRequest>
    suspend fun createSchedule(schedule: Schedule): Result<String>
    suspend fun updateSchedule(schedule: Schedule): Result<Unit>
    suspend fun deleteSchedule(scheduleId: String): Result<Unit>
    suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit>
    suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit>
    suspend fun submitAvailability(scheduleId: String, availability: Map<String, Any>): Result<Unit>

    /**
     * Runs the shift-assignment algorithm for a schedule and persists the resulting
     * grid via the API. Returns the built grid (`[station][day][shift]`).
     */
    suspend fun buildAndSaveSchedule(scheduleId: String): Result<List<List<List<String>>>>

    /** The most recently built grid for a schedule, or null if none has been built. */
    suspend fun getLatestBuiltSchedule(scheduleId: String): List<List<List<String>>>?
}
