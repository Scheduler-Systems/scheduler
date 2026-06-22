package com.schedulersystems.scheduler.data.network.dto

import com.schedulersystems.scheduler.models.domain.Employee
import com.schedulersystems.scheduler.models.domain.EnabledShifts
import com.schedulersystems.scheduler.models.domain.Role
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.ScheduleSettings
import com.schedulersystems.scheduler.models.domain.Shift
import com.schedulersystems.scheduler.models.domain.ShiftRow
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.time.Instant
import java.time.LocalTime

class ScheduleDtoTest {

    @Test
    fun `toDomain maps all fields correctly`() {
        val dto = ScheduleDto(
            id = "schedule-1",
            name = "Test Schedule",
            tenantId = "tenant-1",
            employees = listOf(
                EmployeeDto(
                    id = "emp-1",
                    name = "Alice",
                    email = "alice@test.com",
                    phone = "1234567890",
                    role = "EMPLOYER",
                    priorityMap = mapOf("day1" to 1)
                )
            ),
            currentPriorities = listOf("Alice", "Bob"),
            settings = ScheduleSettingsDto(
                enabledShifts = EnabledShiftsDto(mornings = true, afternoons = false, evenings = true),
                timezone = "America/New_York"
            ),
            nextSchedule = listOf(
                ShiftRowDto(
                    shifts = listOf(
                        ShiftDto(
                            day = "Monday",
                            startTime = "08:00",
                            endTime = "16:00",
                            assignedWorker = "Alice"
                        )
                    )
                )
            ),
            createdAt = "2024-01-01T00:00:00Z",
            updatedAt = "2024-01-02T00:00:00Z"
        )

        val result = dto.toDomain()
        assertEquals("schedule-1", result.id)
        assertEquals("Test Schedule", result.name)
        assertEquals("tenant-1", result.tenantId)
        assertEquals(1, result.employees.size)
        assertEquals("Alice", result.employees[0].name)
        assertEquals(Role.EMPLOYER, result.employees[0].role)
        assertEquals(2, result.currentPriorities.size)
        assertEquals(true, result.settings.enabledShifts.mornings)
        assertEquals(false, result.settings.enabledShifts.afternoons)
        assertEquals(true, result.settings.enabledShifts.evenings)
        assertEquals("America/New_York", result.settings.timezone)
        assertEquals(1, result.nextSchedule.size)
        assertEquals(1, result.nextSchedule[0].shifts.size)
        assertEquals("Monday", result.nextSchedule[0].shifts[0].day)
    }

    @Test
    fun `toDomain handles null id`() {
        val dto = ScheduleDto(
            name = "No ID",
            tenantId = "tenant-1"
        )
        val result = dto.toDomain()
        assertEquals("", result.id)
    }

    @Test
    fun `toDomain handles empty lists`() {
        val dto = ScheduleDto(
            name = "Empty",
            tenantId = "tenant-1"
        )
        val result = dto.toDomain()
        assertEquals(0, result.employees.size)
        assertEquals(0, result.currentPriorities.size)
        assertEquals(0, result.nextSchedule.size)
    }

    @Test
    fun `toDomain handles invalid role gracefully`() {
        val dto = ScheduleDto(
            name = "Bad Role",
            tenantId = "tenant-1",
            employees = listOf(
                EmployeeDto(
                    id = "emp-1",
                    name = "Bob",
                    role = "INVALID_ROLE"
                )
            )
        )
        val result = dto.toDomain()
        assertEquals(Role.EMPLOYEE, result.employees[0].role)
    }

    @Test
    fun `toDomain handles invalid time formats gracefully`() {
        val dto = ScheduleDto(
            name = "Bad Time",
            tenantId = "tenant-1",
            nextSchedule = listOf(
                ShiftRowDto(
                    shifts = listOf(
                        ShiftDto(day = "Monday", startTime = "not_a_time", endTime = "also_bad")
                    )
                )
            )
        )
        val result = dto.toDomain()
        assertEquals(LocalTime.MIDNIGHT, result.nextSchedule[0].shifts[0].startTime)
        assertEquals(LocalTime.MIDNIGHT, result.nextSchedule[0].shifts[0].endTime)
    }

    @Test
    fun `toDomain handles null assignedWorker`() {
        val dto = ScheduleDto(
            name = "No Worker",
            tenantId = "tenant-1",
            nextSchedule = listOf(
                ShiftRowDto(
                    shifts = listOf(
                        ShiftDto(day = "Monday", startTime = "08:00", endTime = "16:00")
                    )
                )
            )
        )
        val result = dto.toDomain()
        assertNull(result.nextSchedule[0].shifts[0].assignedWorker)
    }

    @Test
    fun `toDomain handles missing createdAt and updatedAt`() {
        val dto = ScheduleDto(
            name = "No Dates",
            tenantId = "tenant-1"
        )
        val result = dto.toDomain()
        assertNotNull(result.createdAt)
        assertNotNull(result.updatedAt)
    }

    @Test
    fun `toDomain handles invalid createdAt gracefully`() {
        val dto = ScheduleDto(
            name = "Bad Date",
            tenantId = "tenant-1",
            createdAt = "not-a-date"
        )
        val result = dto.toDomain()
        assertNotNull(result.createdAt)
    }

    @Test
    fun `toDto maps domain back correctly`() {
        val domain = Schedule(
            id = "s-1",
            name = "Test",
            tenantId = "t-1",
            employees = listOf(
                Employee(
                    id = "e-1",
                    name = "Alice",
                    email = "alice@test.com",
                    phone = "555",
                    role = Role.EMPLOYER,
                    priorityMap = mapOf("d1" to 2)
                )
            ),
            currentPriorities = listOf("Alice"),
            settings = ScheduleSettings(
                submissionDeadline = null,
                enabledShifts = EnabledShifts(true, false, true),
                timezone = "UTC"
            ),
            nextSchedule = listOf(
                ShiftRow(
                    shifts = listOf(
                        Shift("Monday", LocalTime.of(8, 0), LocalTime.of(16, 0), "Alice")
                    )
                )
            ),
            createdAt = Instant.parse("2024-01-01T00:00:00Z"),
            updatedAt = Instant.parse("2024-01-02T00:00:00Z")
        )

        val dto = domain.toDto()
        assertEquals("s-1", dto.id)
        assertEquals("Test", dto.name)
        assertEquals("t-1", dto.tenantId)
        assertEquals(1, dto.employees!!.size)
        assertEquals("Alice", dto.employees!![0].name)
        assertEquals("EMPLOYER", dto.employees!![0].role)
        assertEquals(1, dto.nextSchedule!!.size)
    }

    @Test
    fun `toDto handles empty id`() {
        val domain = Schedule(
            id = "",
            name = "Test",
            tenantId = "t-1",
            employees = emptyList(),
            currentPriorities = emptyList(),
            settings = ScheduleSettings(null, EnabledShifts(false, false, false), "UTC"),
            nextSchedule = emptyList(),
            createdAt = Instant.now(),
            updatedAt = Instant.now()
        )
        val dto = domain.toDto()
        assertNull(dto.id)
    }

    @Test
    fun `ScheduleListResponse wraps schedules`() {
        val response = ScheduleListResponse(
            listOf(
                ScheduleDto(name = "S1", tenantId = "t1"),
                ScheduleDto(name = "S2", tenantId = "t2")
            )
        )
        assertEquals(2, response.schedules.size)
    }

    @Test
    fun `EmployeeDto uses default priorityMap`() {
        val dto = EmployeeDto(id = "e1", name = "Test")
        assertEquals(emptyMap<String, Int>(), dto.priorityMap)
    }

    @Test
    fun `EmployeeDto uses default role`() {
        val dto = EmployeeDto(id = "e1", name = "Test")
        assertEquals("EMPLOYEE", dto.role)
    }

    @Test
    fun `ScheduleSettingsDto uses default values`() {
        val dto = ScheduleSettingsDto()
        assertEquals(false, dto.enabledShifts.mornings)
        assertEquals(false, dto.enabledShifts.afternoons)
        assertEquals(false, dto.enabledShifts.evenings)
        assertEquals("UTC", dto.timezone)
    }

    @Test
    fun `toDomain maps archived status (drives the Archived Schedules view)`() {
        val dto = ScheduleDto(name = "Archived Demo", tenantId = "t1", status = "archived")
        assertEquals("archived", dto.toDomain().status)
    }

    @Test
    fun `toDomain defaults missing status to active`() {
        val dto = ScheduleDto(name = "S", tenantId = "t1")
        assertEquals("active", dto.toDomain().status)
    }

    @Test
    fun `toDto round-trips status`() {
        val schedule = Schedule(
            id = "s1", name = "Archived Demo", tenantId = "t1",
            employees = emptyList(), currentPriorities = emptyList(),
            settings = ScheduleSettings(null, EnabledShifts(false, false, false), "UTC"),
            nextSchedule = emptyList(), createdAt = Instant.now(), updatedAt = Instant.now(),
            status = "archived"
        )
        assertEquals("archived", schedule.toDto().status)
    }
}
