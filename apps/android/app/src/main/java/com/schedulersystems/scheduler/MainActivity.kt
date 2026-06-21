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
import com.schedulersystems.scheduler.ui.screens.home.HomeScreen
import com.schedulersystems.scheduler.ui.screens.schedule.ScheduleDetailScreen
import com.schedulersystems.scheduler.ui.screens.schedule.ScheduleListScreen
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
                }
            )
        }

        composable("home") {
            HomeScreen(
                onNavigateToMySchedules = { navController.navigate("scheduleList") },
                onNavigateToNewSchedule = { },
                onNavigateToNotifications = { }
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
                onNavigateBack = { navController.popBackStack() }
            )
        }
    }
}
