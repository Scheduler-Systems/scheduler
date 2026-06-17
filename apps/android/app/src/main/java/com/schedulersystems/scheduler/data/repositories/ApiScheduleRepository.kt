package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.dto.toDomain
import com.schedulersystems.scheduler.data.network.dto.toDto
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Schedule
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ApiScheduleRepository @Inject constructor(
    private val api: SchedulerApi
) : ScheduleRepository {

    private val tenantId = "default"

    override fun getSchedulesForUser(userId: String): Flow<List<Schedule>> = callbackFlow {
        var running = true
        while (running) {
            try {
                val response = api.service.listSchedules(tenantId, userId)
                if (response.isSuccessful) {
                    val list = response.body()?.schedules?.map { it.toDomain() } ?: emptyList()
                    trySend(list)
                }
            } catch (_: Exception) {
            }
            delay(30_000L)
        }
        awaitClose { running = false }
    }

    override suspend fun getScheduleById(scheduleId: String): Schedule? {
        val response = api.service.getSchedule(tenantId, scheduleId)
        if (response.isSuccessful) {
            return response.body()?.toDomain()
        }
        return null
    }

    override suspend fun createSchedule(schedule: Schedule): Result<String> {
        return try {
            val response = api.service.createSchedule(tenantId, schedule.toDto())
            if (response.isSuccessful) {
                Result.success(response.body()?.toDomain()?.id ?: "")
            } else {
                Result.failure(Exception("Failed to create schedule: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun updateSchedule(schedule: Schedule): Result<Unit> {
        return try {
            val response = api.service.updateSchedule(tenantId, schedule.id, schedule.toDto())
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to update schedule: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun deleteSchedule(scheduleId: String): Result<Unit> {
        return try {
            val response = api.service.deleteSchedule(tenantId, scheduleId)
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to delete schedule: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit> {
        return try {
            val schedule = getScheduleById(scheduleId) ?: return Result.failure(Exception("Schedule not found"))
            val updated = schedule.copy(employees = schedule.employees + employee)
            updateSchedule(updated)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit> {
        return try {
            val schedule = getScheduleById(scheduleId) ?: return Result.failure(Exception("Schedule not found"))
            val updated = schedule.copy(employees = schedule.employees.filter { it.id != employeeId })
            updateSchedule(updated)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }
}
