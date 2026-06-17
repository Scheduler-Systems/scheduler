package com.schedulersystems.scheduler.repositories

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.schedulersystems.scheduler.data.repositories.ScheduleRepository
import com.schedulersystems.scheduler.models.domain.*
import dagger.hilt.android.testing.HiltAndroidRule
import dagger.hilt.android.testing.HiltAndroidTest
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Instant
import java.time.LocalTime
import javax.inject.Inject

@RunWith(AndroidJUnit4::class)
@HiltAndroidTest
class ScheduleRepositoryIntegrationTest {

    @get:Rule
    val hiltRule = HiltAndroidRule(this)

    @Inject
    lateinit var scheduleRepository: ScheduleRepository

    private val testEmployee = Employee(
        id = "emp-1",
        name = "Test Employee",
        email = "emp@example.com",
        phone = null,
        role = Role.EMPLOYEE,
        priorityMap = emptyMap()
    )

    private val testSchedule = Schedule(
        id = "sched-1",
        name = "Test Schedule",
        tenantId = "tenant-1",
        employees = listOf(testEmployee),
        currentPriorities = listOf("priority-1"),
        settings = ScheduleSettings(
            submissionDeadline = null,
            enabledShifts = EnabledShifts(
                mornings = true,
                afternoons = true,
                evenings = false
            ),
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

    @Before
    fun setup() {
        hiltRule.inject()
    }

    @Test
    fun shouldGetSchedulesForUser() = runBlocking {
        val schedules = scheduleRepository.getSchedulesForUser("test-id").first()

        assertTrue(schedules.isNotEmpty())
        assertEquals("Test Schedule", schedules.first().name)
    }

    @Test
    fun shouldGetScheduleById() = runBlocking {
        val schedule = scheduleRepository.getScheduleById("sched-1")

        assertNotNull(schedule)
        assertEquals("Test Schedule", schedule?.name)
    }

    @Test
    fun shouldCreateSchedule() = runBlocking {
        val result = scheduleRepository.createSchedule(testSchedule)

        assertTrue(result.isSuccess)
        assertEquals("new-id", result.getOrNull())
    }

    @Test
    fun shouldUpdateSchedule() = runBlocking {
        val result = scheduleRepository.updateSchedule(testSchedule)

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldDeleteSchedule() = runBlocking {
        val result = scheduleRepository.deleteSchedule("sched-1")

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldAddEmployee() = runBlocking {
        val result = scheduleRepository.addEmployee("sched-1", testEmployee)

        assertTrue(result.isSuccess)
    }

    @Test
    fun shouldRemoveEmployee() = runBlocking {
        val result = scheduleRepository.removeEmployee("sched-1", "emp-1")

        assertTrue(result.isSuccess)
    }
}
