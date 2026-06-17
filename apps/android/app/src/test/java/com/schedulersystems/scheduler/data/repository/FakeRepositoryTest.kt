package com.schedulersystems.scheduler.data.repository

import com.schedulersystems.scheduler.di.FakeAuthRepository
import com.schedulersystems.scheduler.di.FakeScheduleRepository
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.Instant

class FakeRepositoryTest {

    @Test
    fun `fake auth repository should return configured user`() = runTest {
        val repo = FakeAuthRepository()

        val user = repo.currentUser.first()
        assertNotNull(user)
        assertEquals("test-id", user?.id)
    }

    @Test
    fun `fake auth repository should return configurable results`() = runTest {
        val repo = FakeAuthRepository()
        repo.signInResult = Result.failure(Exception("Custom error"))

        val result = repo.signInWithEmail("test@test.com", "wrong")
        assertTrue(result.isFailure)
        assertEquals("Custom error", result.exceptionOrNull()?.message)
    }

    @Test
    fun `fake auth repository should return authenticated flow`() = runTest {
        val repo = FakeAuthRepository()
        val isAuth = repo.isAuthenticated.first()
        assertTrue(isAuth)
    }

    @Test
    fun `fake auth repository phone sign in`() = runTest {
        val repo = FakeAuthRepository()
        val result = repo.signInWithPhone("+1234567890")
        assertTrue(result.isSuccess)
        assertEquals("verification-id-123", result.getOrNull())
    }

    @Test
    fun `fake auth repository google sign in`() = runTest {
        val repo = FakeAuthRepository()
        val result = repo.signInWithGoogle("google-token")
        assertTrue(result.isSuccess)
        assertEquals("Google User", result.getOrNull()?.displayName)
    }

    @Test
    fun `fake schedule repository should return configured schedules`() = runTest {
        val repo = FakeScheduleRepository()
        val schedule = Schedule(
            "s-1", "Test Schedule", "t-1", emptyList(), emptyList(),
            ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            emptyList(), Instant.now(), Instant.now()
        )
        repo.schedules = listOf(schedule)

        val result = repo.getSchedulesForUser("user-1").first()
        assertEquals(1, result.size)
        assertEquals("Test Schedule", result[0].name)
    }

    @Test
    fun `fake schedule repository should return schedule by id`() = runTest {
        val repo = FakeScheduleRepository()
        val schedule = Schedule(
            "s-1", "Test Schedule", "t-1", emptyList(), emptyList(),
            ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            emptyList(), Instant.now(), Instant.now()
        )
        repo.schedules = listOf(schedule)

        val result = repo.getScheduleById("s-1")
        assertNotNull(result)
        assertEquals("Test Schedule", result?.name)

        val missing = repo.getScheduleById("nonexistent")
        assertNull(missing)
    }

    @Test
    fun `fake schedule repository should report create success`() = runTest {
        val repo = FakeScheduleRepository()
        val schedule = Schedule(
            "", "New", "t-1", emptyList(), emptyList(),
            ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            emptyList(), Instant.now(), Instant.now()
        )

        val result = repo.createSchedule(schedule)
        assertTrue(result.isSuccess)
        assertEquals("new-schedule-id", result.getOrNull())
    }

    @Test
    fun `fake schedule repository should report create failure`() = runTest {
        val repo = FakeScheduleRepository()
        repo.createResult = Result.failure(Exception("Create failed"))
        val schedule = Schedule(
            "", "New", "t-1", emptyList(), emptyList(),
            ScheduleSettings(null, EnabledShifts(true, true, false), "UTC"),
            emptyList(), Instant.now(), Instant.now()
        )

        val result = repo.createSchedule(schedule)
        assertTrue(result.isFailure)
    }

    @Test
    fun `fake schedule repository should add employee`() = runTest {
        val repo = FakeScheduleRepository()
        val employee = Employee("e-1", "Alice", null, null, Role.EMPLOYEE, emptyMap())
        val result = repo.addEmployee("s-1", employee)
        assertTrue(result.isSuccess)
    }

    @Test
    fun `fake schedule repository should remove employee`() = runTest {
        val repo = FakeScheduleRepository()
        val result = repo.removeEmployee("s-1", "e-1")
        assertTrue(result.isSuccess)
    }
}
