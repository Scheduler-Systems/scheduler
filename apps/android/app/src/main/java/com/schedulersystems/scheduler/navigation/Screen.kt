package com.schedulersystems.scheduler.navigation

sealed class Screen(val route: String) {
    object PhoneSignIn : Screen("phoneSignIn")
    object PhoneCode : Screen("phoneCode")
    object EmailLogin : Screen("loginEmail")
    object CreateAccount : Screen("createAccountEmail")
    object PasswordReset : Screen("passwordReset")
    object VerifyEmail : Screen("verifyEmailWaiting")
    object GetName : Screen("getName")
    object ChooseRole : Screen("chooseRole")
    object Onboarding : Screen("onboarding")
    
    object Home : Screen("home")
    object MySchedules : Screen("mySchedules")
    object NewSchedule1 : Screen("newSchedule1")
    object NewSchedule2 : Screen("newSchedule2?scheduleName={scheduleName}")
    object ScheduleSettings : Screen("scheduleSettings/{scheduleId}")
    object ScheduleBuild : Screen("scheduleBuild/{scheduleId}")
    object ArchivedSchedules : Screen("archivedSchedules/{scheduleId}")
    
    object EmployeeList : Screen("employeeList/{scheduleName}")
    object AddEmployee : Screen("addEmployee")
    
    object PrioritiesSubmission : Screen("prioritiesSubmission/{scheduleId}")
    object CurrentPriorities : Screen("currentPriorities/{scheduleId}")
    object ScheduleRequest : Screen("scheduleRequest/{requestId}")
    object ShiftChangeRequests : Screen("shiftChangeRequests")
    
    object ChatMain : Screen("chat2Main")
    object ChatDetails : Screen("chat2Details/{chatId}")
    object ChatInvite : Screen("chat2InviteUsers")
    
    object ExportShifts : Screen("exportShifts/{scheduleId}")
    object SharePdf : Screen("sharePdf/{scheduleId}")
    
    object ProfileSettings : Screen("profileSettings")
    
    object Gemini : Screen("geminiScreen?scheduleName={scheduleName}")
}
