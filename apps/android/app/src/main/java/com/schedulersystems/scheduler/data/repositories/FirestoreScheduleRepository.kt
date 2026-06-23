package com.schedulersystems.scheduler.data.repositories

import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleRequest
import com.schedulersystems.scheduler.models.domain.User
import com.schedulersystems.scheduler.models.domain.Employee
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.FieldValue
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.tasks.await
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class FirestoreScheduleRepository @Inject constructor(
    private val firestore: FirebaseFirestore
) : ScheduleRepository {

    override fun getSchedulesForUser(userId: String): Flow<List<Schedule>> = callbackFlow {
        val listener = firestore.collection("schedules")
            .whereArrayContains("employee_ids", userId)
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    close(error)
                    return@addSnapshotListener
                }
                val schedules = snapshot?.documents?.mapNotNull { doc ->
                    doc.toSchedule()
                } ?: emptyList()
                trySend(schedules)
            }
        awaitClose { listener.remove() }
    }

    override suspend fun getScheduleById(scheduleId: String): Schedule? {
        val doc = firestore.collection("schedules").document(scheduleId).get().await()
        return doc.toSchedule()
    }

    // Firestore embeds the roster in the schedule document.
    override suspend fun getEmployees(scheduleId: String): List<Employee> {
        return getScheduleById(scheduleId)?.employees ?: emptyList()
    }

    // Invitations are served by the Go API (ApiScheduleRepository); the legacy Firestore
    // path doesn't expose them.
    override suspend fun getInvitations(scheduleId: String): List<com.schedulersystems.scheduler.models.domain.ScheduleRequest> = emptyList()

    override suspend fun createSchedule(schedule: Schedule): Result<String> {
        return try {
            val docRef = firestore.collection("schedules").document()
            val data = schedule.toMap().toMutableMap().apply {
                put("id", docRef.id)
            }
            docRef.set(data).await()
            Result.success(docRef.id)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun updateSchedule(schedule: Schedule): Result<Unit> {
        return try {
            firestore.collection("schedules").document(schedule.id)
                .update(schedule.toMap()).await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun deleteSchedule(scheduleId: String): Result<Unit> {
        return try {
            firestore.collection("schedules").document(scheduleId).delete().await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun addEmployee(scheduleId: String, employee: Employee): Result<Unit> {
        return try {
            firestore.collection("schedules").document(scheduleId)
                .update("employees", FieldValue.arrayUnion(employee.toMap()))
                .await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    override suspend fun removeEmployee(scheduleId: String, employeeId: String): Result<Unit> {
        return try {
            val schedule = getScheduleById(scheduleId) ?: return Result.failure(Exception("Schedule not found"))
            val employee = schedule.employees.find { it.id == employeeId }
                ?: return Result.failure(Exception("Employee not found"))
            firestore.collection("schedules").document(scheduleId)
                .update("employees", FieldValue.arrayRemove(employee.toMap()))
                .await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    // Availability submission is served by the Go API (ApiScheduleRepository); the legacy
    // Firestore path is unused for this and succeeds as a no-op.
    override suspend fun submitAvailability(scheduleId: String, availability: Map<String, Any>): Result<Unit> =
        Result.success(Unit)

    // Schedule-build persistence is served by the Go API (ApiScheduleRepository, the bound
    // impl); the legacy Firestore path is unused for it.
    override suspend fun buildAndSaveSchedule(scheduleId: String): Result<List<List<List<String>>>> =
        Result.failure(UnsupportedOperationException("buildAndSaveSchedule is served by the Go API"))

    override suspend fun getLatestBuiltSchedule(scheduleId: String): List<List<List<String>>>? = null

    suspend fun getScheduleByName(scheduleName: String): Schedule? {
        val snapshot = firestore.collection("schedules")
            .whereEqualTo("schedule_name", scheduleName)
            .limit(1)
            .get()
            .await()
        return snapshot.documents.firstOrNull()?.toSchedule()
    }

    fun getScheduleRequests(scheduleId: String, isAddRequest: Boolean): Flow<List<ScheduleRequest>> = callbackFlow {
        val listener = firestore.collection("schedule_requests")
            .whereEqualTo("schedule_ref", scheduleId)
            .whereEqualTo("is_add_request", isAddRequest)
            .whereEqualTo("request_status", "ADD_REQUEST_PENDING")
            .addSnapshotListener { snapshot, error ->
                if (error != null) {
                    close(error)
                    return@addSnapshotListener
                }
                val requests = snapshot?.documents?.mapNotNull { doc ->
                    doc.toScheduleRequest()
                } ?: emptyList()
                trySend(requests)
            }
        awaitClose { listener.remove() }
    }

    suspend fun deleteScheduleRequest(requestId: String): Result<Unit> {
        return try {
            firestore.collection("schedule_requests").document(requestId).delete().await()
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun getUserById(userId: String): User? {
        val doc = firestore.collection("users").document(userId).get().await()
        return doc.toUser()
    }

    suspend fun getUserByEmail(email: String): User? {
        val snapshot = firestore.collection("users")
            .whereEqualTo("email", email)
            .limit(1)
            .get()
            .await()
        return snapshot.documents.firstOrNull()?.toUser()
    }

    suspend fun updateProfile(userId: String, displayName: String?, photoUrl: String?): Result<Unit> {
        return try {
            val updates = mutableMapOf<String, Any>()
            displayName?.let { updates["display_name"] = it }
            photoUrl?.let { updates["photo_url"] = it }
            if (updates.isNotEmpty()) {
                firestore.collection("users").document(userId).update(updates).await()
            }
            Result.success(Unit)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun com.google.firebase.firestore.DocumentSnapshot.toSchedule(): Schedule? {
        return try {
            val data = data ?: return null
            Schedule(
                id = id,
                name = data["schedule_name"] as? String ?: "",
                tenantId = data["tenant_id"] as? String ?: "",
                employees = (data["employees"] as? List<Map<String, Any>>)?.map { it.toEmployee() } ?: emptyList(),
                currentPriorities = (data["current_priorities"] as? List<String>) ?: emptyList(),
                settings = (data["schedule_settings"] as? Map<String, Any>)?.toScheduleSettings() 
                    ?: com.schedulersystems.scheduler.models.domain.ScheduleSettings(
                        submissionDeadline = null,
                        enabledShifts = com.schedulersystems.scheduler.models.domain.EnabledShifts(
                            mornings = false,
                            afternoons = false,
                            evenings = false
                        ),
                        timezone = "UTC"
                    ),
                nextSchedule = emptyList(),
                createdAt = java.time.Instant.now(),
                updatedAt = java.time.Instant.now()
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun Map<String, Any>.toEmployee(): Employee {
        return Employee(
            id = this["id"] as? String ?: "",
            name = this["name"] as? String ?: "",
            email = this["email"] as? String,
            phone = this["phone"] as? String,
            role = try {
                com.schedulersystems.scheduler.models.domain.Role.valueOf((this["role"] as? String ?: "EMPLOYEE").uppercase())
            } catch (e: Exception) {
                com.schedulersystems.scheduler.models.domain.Role.EMPLOYEE
            },
            priorityMap = (this["priority_map"] as? Map<String, Int>) ?: emptyMap()
        )
    }

    private fun Map<String, Any>.toScheduleSettings(): com.schedulersystems.scheduler.models.domain.ScheduleSettings {
        val enabledShifts = (this["enabled_shifts"] as? Map<String, Any>)?.let { shifts ->
            com.schedulersystems.scheduler.models.domain.EnabledShifts(
                mornings = shifts["morning"] as? Boolean ?: false,
                afternoons = shifts["afternoon"] as? Boolean ?: false,
                evenings = shifts["night"] as? Boolean ?: false
            )
        } ?: com.schedulersystems.scheduler.models.domain.EnabledShifts(false, false, false)
        
        return com.schedulersystems.scheduler.models.domain.ScheduleSettings(
            submissionDeadline = null,
            enabledShifts = enabledShifts,
            timezone = this["timezone"] as? String ?: "UTC"
        )
    }

    private fun com.google.firebase.firestore.DocumentSnapshot.toScheduleRequest(): ScheduleRequest? {
        return try {
            val data = data ?: return null
            ScheduleRequest(
                id = id,
                scheduleName = data["schedule_name"] as? String ?: "",
                scheduleRef = data["schedule_ref"] as? String ?: "",
                fromUser = data["from_user"] as? String,
                toUser = data["to_user"] as? String,
                toUserIdentification = data["to_user_identification"] as? String ?: "",
                isAddRequest = data["is_add_request"] as? Boolean ?: false,
                isJoinRequest = data["is_join_request"] as? Boolean ?: false,
                requestStatus = try {
                    com.schedulersystems.scheduler.models.domain.RequestStatus.valueOf(
                        (data["request_status"] as? String ?: "ADD_REQUEST_PENDING").uppercase()
                    )
                } catch (e: Exception) {
                    com.schedulersystems.scheduler.models.domain.RequestStatus.ADD_REQUEST_PENDING
                },
                isRead = data["is_read"] as? Boolean ?: false,
                createdTime = java.time.Instant.now()
            )
        } catch (e: Exception) {
            null
        }
    }

    private fun com.google.firebase.firestore.DocumentSnapshot.toUser(): User? {
        return try {
            val data = data ?: return null
            User(
                id = id,
                email = data["email"] as? String,
                phone = data["phone_number"] as? String,
                displayName = data["display_name"] as? String,
                role = try {
                    com.schedulersystems.scheduler.models.domain.Role.valueOf(
                        (data["role"] as? String ?: "EMPLOYEE").uppercase()
                    )
                } catch (e: Exception) {
                    null
                },
                isPremium = data["is_premium"] as? Boolean ?: false,
                tenantId = data["tenant_id"] as? String
            )
        } catch (e: Exception) {
            null
        }
    }
}

private fun Schedule.toMap(): Map<String, Any?> {
    return mapOf(
        "schedule_name" to name,
        "tenant_id" to tenantId,
        "employees" to employees.map { it.toMap() },
        "current_priorities" to currentPriorities,
        "schedule_settings" to mapOf(
            "enabled_shifts" to mapOf(
                "morning" to settings.enabledShifts.mornings,
                "afternoon" to settings.enabledShifts.afternoons,
                "night" to settings.enabledShifts.evenings
            ),
            "timezone" to settings.timezone
        )
    )
}

private fun Employee.toMap(): Map<String, Any?> {
    return mapOf(
        "id" to id,
        "name" to name,
        "email" to email,
        "phone" to phone,
        "role" to role.name,
        "priority_map" to priorityMap
    )
}
