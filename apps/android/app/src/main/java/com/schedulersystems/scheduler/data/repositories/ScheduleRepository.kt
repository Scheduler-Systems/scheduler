package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.Employee
import kotlinx.coroutines.flow.Flow

interface ScheduleRepository {
    fun getSchedulesForUser(userId: String): Flow<List<Schedule>>
    suspend fun getScheduleById(scheduleId: String): Schedule?
    suspend fun createSchedule(schedule: Schedule): Result<String>
    suspend fun updateSchedule(schedule: Schedule): Result<Unit>
    suspend fun deleteSchedule(scheduleId: String): Result<Unit>
    suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit>
    suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit>
}
