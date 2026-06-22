package com.schedulersystems.scheduler

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.schedulersystems.scheduler.ui.screens.auth.CreateAccountScreen
import com.schedulersystems.scheduler.ui.screens.auth.LoginScreen
import com.schedulersystems.scheduler.ui.screens.auth.PasswordResetScreen
import com.schedulersystems.scheduler.ui.screens.auth.PhoneSignInScreen
import com.schedulersystems.scheduler.ui.screens.auth.VerifyEmailScreen
import com.schedulersystems.scheduler.ui.screens.employees.EmployeeListScreen
import com.schedulersystems.scheduler.ui.screens.home.HomeScreen
import com.schedulersystems.scheduler.ui.screens.profile.ProfileSettingsScreen
import com.schedulersystems.scheduler.ui.screens.priorities.PrioritiesSubmissionScreen
import com.schedulersystems.scheduler.ui.screens.policies.PoliciesScreen
import com.schedulersystems.scheduler.ui.screens.priority.CurrentPrioritiesScreen
import com.schedulersystems.scheduler.ui.screens.requests.ScheduleRequestsScreen
import com.schedulersystems.scheduler.ui.screens.schedule.ArchivedSchedulesScreen
import com.schedulersystems.scheduler.ui.screens.schedule.NewScheduleScreen
import com.schedulersystems.scheduler.ui.screens.schedule.ScheduleDetailScreen
import com.schedulersystems.scheduler.ui.screens.schedule.ScheduleListScreen
import com.schedulersystems.scheduler.ui.screens.settings.ScheduleSettingsScreen
import com.schedulersystems.scheduler.ui.theme.SchedulerTheme
import dagger.hilt.android.AndroidEntryPoint

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            SchedulerTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    val navController = rememberNavController()
                    SchedulerNavHost(navController)
                }
            }
        }
    }
}

@Composable
fun SchedulerNavHost(
    navController: NavHostController,
    startDestination: String = "login"
) {
    NavHost(
        navController = navController,
        startDestination = startDestination
    ) {
        composable("login") {
            LoginScreen(
                onNavigateToPhoneSignIn = { navController.navigate("phoneSignIn") },
                onNavigateToEmailSignIn = { },
                onNavigateToSignUp = { navController.navigate("createAccount") },
                onNavigateToPasswordReset = { navController.navigate("passwordReset") },
                onNavigateToHome = { 
                    navController.navigate("home") {
                        popUpTo("login") { inclusive = true }
                    }
                }
            )
        }
        
        composable("phoneSignIn") {
            PhoneSignInScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToPhoneCode = { },
                onNavigateToHome = {
                    navController.navigate("home") {
                        popUpTo("login") { inclusive = true }
                    }
                }
            )
        }

        composable("passwordReset") {
            PasswordResetScreen(
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("createAccount") {
            CreateAccountScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToHome = {
                    navController.navigate("home") {
                        popUpTo("login") { inclusive = true }
                    }
                },
                onNavigateToVerifyEmail = {
                    navController.navigate("verifyEmail") {
                        popUpTo("login") { inclusive = true }
                    }
                }
            )
        }

        composable("verifyEmail") {
            VerifyEmailScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToHome = {
                    navController.navigate("home") {
                        popUpTo("login") { inclusive = true }
                    }
                }
            )
        }

        composable("home") {
            HomeScreen(
                onNavigateToMySchedules = { navController.navigate("scheduleList") },
                onNavigateToNewSchedule = { navController.navigate("newSchedule") },
                onNavigateToArchived = { navController.navigate("archivedSchedules") },
                onNavigateToProfile = { navController.navigate("profile") },
                onNavigateToPolicies = { navController.navigate("policies") },
                onNavigateToNotifications = { }
            )
        }

        composable("archivedSchedules") {
            ArchivedSchedulesScreen(
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("profile") {
            ProfileSettingsScreen(
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("newSchedule") {
            NewScheduleScreen(
                onNavigateBack = { navController.popBackStack() },
                onCreated = {
                    // Land on My Schedules so the new schedule is visible; drop the
                    // create screen from the back stack.
                    navController.navigate("scheduleList") {
                        popUpTo("newSchedule") { inclusive = true }
                    }
                }
            )
        }
        
        composable("scheduleList") {
            ScheduleListScreen(
                onNavigateBack = { navController.popBackStack() },
                onNavigateToScheduleDetail = { scheduleId ->
                    navController.navigate("scheduleDetail/$scheduleId")
                }
            )
        }
        
        composable("scheduleDetail/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            ScheduleDetailScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() },
                onNavigateToEmployeeList = { navController.navigate("employeeList/$scheduleId") },
                onNavigateToSettings = { navController.navigate("scheduleSettings/$scheduleId") },
                onNavigateToRequests = { navController.navigate("scheduleRequests/$scheduleId") },
                onNavigateToPriorities = { navController.navigate("prioritiesSubmission/$scheduleId") },
                onNavigateToCurrentPriorities = { navController.navigate("currentPriorities/$scheduleId") }
            )
        }

        composable("scheduleSettings/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            ScheduleSettingsScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("scheduleRequests/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            ScheduleRequestsScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("employeeList/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            EmployeeListScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("prioritiesSubmission/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            PrioritiesSubmissionScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("currentPriorities/{scheduleId}") { backStackEntry ->
            val scheduleId = backStackEntry.arguments?.getString("scheduleId") ?: ""
            CurrentPrioritiesScreen(
                scheduleId = scheduleId,
                onNavigateBack = { navController.popBackStack() }
            )
        }

        composable("policies") {
            PoliciesScreen(onNavigateBack = { navController.popBackStack() })
        }
    }
}
