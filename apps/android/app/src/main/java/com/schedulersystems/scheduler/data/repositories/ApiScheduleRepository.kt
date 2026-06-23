package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.data.network.SchedulerApi
import com.schedulersystems.scheduler.data.network.dto.AvailabilityRequestDto
import com.schedulersystems.scheduler.data.network.dto.BuiltScheduleSaveRequest
import com.schedulersystems.scheduler.data.network.dto.toAddRequest
import com.schedulersystems.scheduler.domain.scheduling.AssignShiftsInput
import com.schedulersystems.scheduler.domain.scheduling.PartialStationConfig
import com.schedulersystems.scheduler.domain.scheduling.assignShifts
import com.schedulersystems.scheduler.data.network.dto.toDomain
import com.schedulersystems.scheduler.data.network.dto.toDto
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Schedule
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.first
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class ApiScheduleRepository @Inject constructor(
    private val api: SchedulerApi,
    private val authRepository: AuthRepository
) : ScheduleRepository {

    // The app's tenant is the signed-in user's id (single-user tenancy; matches iOS).
    private suspend fun currentTenant(): String = authRepository.currentUser.first()?.id ?: "default"

    override fun getSchedulesForUser(userId: String): Flow<List<Schedule>> = callbackFlow {
        var running = true
        while (running) {
            try {
                val response = api.service.listSchedules(userId, userId)
                if (response.isSuccessful) {
                    val list = response.body()?.schedules?.map { it.toDomain() } ?: emptyList()
                    trySend(list)
                } else {
                    android.util.Log.e("ApiSchedRepo", "listSchedules HTTP ${response.code()}")
                }
            } catch (e: Exception) {
                // Don't swallow silently — surfacing this caught a chain of real wiring bugs.
                android.util.Log.e("ApiSchedRepo", "listSchedules failed", e)
            }
            delay(30_000L)
        }
        awaitClose { running = false }
    }

    override suspend fun getScheduleById(scheduleId: String): Schedule? {
        val response = api.service.getSchedule(currentTenant(), scheduleId)
        if (response.isSuccessful) {
            return response.body()?.toDomain()
        }
        return null
    }

    override suspend fun getEmployees(scheduleId: String): List<Employee> {
        return try {
            val response = api.service.listEmployees(currentTenant(), scheduleId)
            if (response.isSuccessful) {
                response.body()?.items?.map { it.toDomain() } ?: emptyList()
            } else {
                android.util.Log.e("ApiSchedRepo", "listEmployees HTTP ${response.code()}")
                emptyList()
            }
        } catch (e: Exception) {
            android.util.Log.e("ApiSchedRepo", "listEmployees failed", e)
            emptyList()
        }
    }

    override suspend fun getInvitations(scheduleId: String): List<com.schedulersystems.scheduler.models.domain.ScheduleRequest> {
        return try {
            val response = api.service.listInvitations(currentTenant(), scheduleId)
            if (response.isSuccessful) {
                response.body()?.items?.map { it.toDomain() } ?: emptyList()
            } else {
                android.util.Log.e("ApiSchedRepo", "listInvitations HTTP ${response.code()}")
                emptyList()
            }
        } catch (e: Exception) {
            android.util.Log.e("ApiSchedRepo", "listInvitations failed", e)
            emptyList()
        }
    }

    override suspend fun createSchedule(schedule: Schedule): Result<String> {
        return try {
            val response = api.service.createSchedule(currentTenant(), schedule.toDto())
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
            val response = api.service.updateSchedule(currentTenant(), schedule.id, schedule.toDto())
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
            val response = api.service.deleteSchedule(currentTenant(), scheduleId)
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to delete schedule: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // Employees live behind their own endpoint, not embedded in the schedule, so
    // add/remove POST/DELETE directly against it (the previous read-modify-write of
    // the whole schedule silently no-op'd — the server ignores a schedule.employees body).
    override suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit> {
        return try {
            val response = api.service.addEmployee(currentTenant(), scheduleId, employee.toAddRequest())
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to add employee: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // employeeId is the employee email (the API's stable identity; see EmployeeApiDto).
    override suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit> {
        return try {
            val response = api.service.removeEmployee(currentTenant(), scheduleId, employeeId)
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to remove employee: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun submitAvailability(scheduleId: String, availability: Map<String, Any>): Result<Unit> {
        return try {
            val response = api.service.submitAvailability(
                currentTenant(), scheduleId, AvailabilityRequestDto(availability)
            )
            if (response.isSuccessful) {
                Result.success(Unit)
            } else {
                Result.failure(Exception("Failed to submit availability: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun buildAndSaveSchedule(scheduleId: String): Result<List<List<List<String>>>> {
        return try {
            val schedule = getScheduleById(scheduleId)
                ?: return Result.failure(Exception("Schedule not found"))
            val shifts = schedule.settings.enabledShifts
            val input = AssignShiftsInput(
                currentPriorities = schedule.currentPriorities,
                stationNum = 1,
                numOfPeople = schedule.employees.size.coerceAtLeast(1),
                stations = listOf(
                    PartialStationConfig(
                        morning = shifts.mornings,
                        afternoon = shifts.afternoons,
                        night = shifts.evenings
                    )
                )
            )
            // Real assignment algorithm; map the assigner's nullable cells → "" for the
            // API (Go grid is [][][]string and an empty cell renders the same either way).
            val grid = assignShifts(input).grids.map { station ->
                station.map { day -> day.map { it ?: "" } }
            }
            val response = api.service.saveBuiltSchedule(
                currentTenant(), scheduleId,
                BuiltScheduleSaveRequest(schedule = grid, currentPriorities = schedule.currentPriorities)
            )
            if (response.isSuccessful) {
                Result.success(response.body()?.schedule ?: grid)
            } else {
                Result.failure(Exception("Failed to save built schedule: ${response.code()}"))
            }
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun getLatestBuiltSchedule(scheduleId: String): List<List<List<String>>>? {
        return try {
            val response = api.service.getLatestBuiltSchedule(currentTenant(), scheduleId)
            if (response.isSuccessful) response.body()?.schedule else null
        } catch (e: Exception) {
            null
        }
    }
}
