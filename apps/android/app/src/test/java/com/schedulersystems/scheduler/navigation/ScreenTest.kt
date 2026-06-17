package com.schedulersystems.scheduler.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenTest {

    @Test
    fun `PhoneSignIn has correct route`() {
        assertEquals("phoneSignIn", Screen.PhoneSignIn.route)
    }

    @Test
    fun `PhoneCode has correct route`() {
        assertEquals("phoneCode", Screen.PhoneCode.route)
    }

    @Test
    fun `EmailLogin has correct route`() {
        assertEquals("loginEmail", Screen.EmailLogin.route)
    }

    @Test
    fun `CreateAccount has correct route`() {
        assertEquals("createAccountEmail", Screen.CreateAccount.route)
    }

    @Test
    fun `PasswordReset has correct route`() {
        assertEquals("passwordReset", Screen.PasswordReset.route)
    }

    @Test
    fun `VerifyEmail has correct route`() {
        assertEquals("verifyEmailWaiting", Screen.VerifyEmail.route)
    }

    @Test
    fun `GetName has correct route`() {
        assertEquals("getName", Screen.GetName.route)
    }

    @Test
    fun `ChooseRole has correct route`() {
        assertEquals("chooseRole", Screen.ChooseRole.route)
    }

    @Test
    fun `Onboarding has correct route`() {
        assertEquals("onboarding", Screen.Onboarding.route)
    }

    @Test
    fun `Home has correct route`() {
        assertEquals("home", Screen.Home.route)
    }

    @Test
    fun `MySchedules has correct route`() {
        assertEquals("mySchedules", Screen.MySchedules.route)
    }

    @Test
    fun `NewSchedule1 has correct route`() {
        assertEquals("newSchedule1", Screen.NewSchedule1.route)
    }

    @Test
    fun `NewSchedule2 has correct route`() {
        assertTrue(Screen.NewSchedule2.route.contains("newSchedule2"))
    }

    @Test
    fun `ScheduleSettings has correct route`() {
        assertTrue(Screen.ScheduleSettings.route.contains("scheduleSettings"))
    }

    @Test
    fun `ScheduleBuild has correct route`() {
        assertTrue(Screen.ScheduleBuild.route.contains("scheduleBuild"))
    }

    @Test
    fun `ArchivedSchedules has correct route`() {
        assertTrue(Screen.ArchivedSchedules.route.contains("archivedSchedules"))
    }

    @Test
    fun `EmployeeList has correct route`() {
        assertTrue(Screen.EmployeeList.route.contains("employeeList"))
    }

    @Test
    fun `AddEmployee has correct route`() {
        assertEquals("addEmployee", Screen.AddEmployee.route)
    }

    @Test
    fun `PrioritiesSubmission has correct route`() {
        assertTrue(Screen.PrioritiesSubmission.route.contains("prioritiesSubmission"))
    }

    @Test
    fun `CurrentPriorities has correct route`() {
        assertTrue(Screen.CurrentPriorities.route.contains("currentPriorities"))
    }

    @Test
    fun `ScheduleRequest has correct route`() {
        assertTrue(Screen.ScheduleRequest.route.contains("scheduleRequest"))
    }

    @Test
    fun `ShiftChangeRequests has correct route`() {
        assertEquals("shiftChangeRequests", Screen.ShiftChangeRequests.route)
    }

    @Test
    fun `ChatMain has correct route`() {
        assertEquals("chat2Main", Screen.ChatMain.route)
    }

    @Test
    fun `ChatDetails has correct route`() {
        assertTrue(Screen.ChatDetails.route.contains("chat2Details"))
    }

    @Test
    fun `ChatInvite has correct route`() {
        assertEquals("chat2InviteUsers", Screen.ChatInvite.route)
    }

    @Test
    fun `ExportShifts has correct route`() {
        assertTrue(Screen.ExportShifts.route.contains("exportShifts"))
    }

    @Test
    fun `SharePdf has correct route`() {
        assertTrue(Screen.SharePdf.route.contains("sharePdf"))
    }

    @Test
    fun `ProfileSettings has correct route`() {
        assertEquals("profileSettings", Screen.ProfileSettings.route)
    }

    @Test
    fun `Gemini has correct route`() {
        assertTrue(Screen.Gemini.route.contains("geminiScreen"))
    }

    @Test
    fun `all routes are non-empty`() {
        val screens = listOf(
            Screen.PhoneSignIn, Screen.PhoneCode, Screen.EmailLogin,
            Screen.CreateAccount, Screen.PasswordReset, Screen.VerifyEmail,
            Screen.GetName, Screen.ChooseRole, Screen.Onboarding,
            Screen.Home, Screen.MySchedules, Screen.NewSchedule1,
            Screen.NewSchedule2, Screen.ScheduleSettings, Screen.ScheduleBuild,
            Screen.ArchivedSchedules, Screen.EmployeeList, Screen.AddEmployee,
            Screen.PrioritiesSubmission, Screen.CurrentPriorities, Screen.ScheduleRequest,
            Screen.ShiftChangeRequests, Screen.ChatMain, Screen.ChatDetails,
            Screen.ChatInvite, Screen.ExportShifts, Screen.SharePdf,
            Screen.ProfileSettings, Screen.Gemini
        )
        screens.forEach {
            assertTrue("${it.route} should not be empty", it.route.isNotEmpty())
        }
    }
}
