package com.schedulersystems.scheduler.ui.screens.home

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.schedulersystems.scheduler.models.domain.Role
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(
    onNavigateToMySchedules: () -> Unit,
    onNavigateToNewSchedule: () -> Unit,
    onNavigateToArchived: () -> Unit,
    onNavigateToProfile: () -> Unit,
    onNavigateToNotifications: () -> Unit,
    viewModel: HomeViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                DrawerContent(
                    displayName = state.displayName,
                    userRole = state.userRole,
                    isPremium = state.isPremium
                )
            }
        }
    ) {
        Scaffold(
            topBar = {
                TopAppBar(
                    title = {
                        Box(
                            modifier = Modifier.fillMaxWidth(),
                            contentAlignment = Alignment.Center
                        ) {
                            Text(
                                text = "Home",
                                fontSize = 22.sp,
                                fontWeight = FontWeight.Medium,
                                color = Color.White
                            )
                        }
                    },
                    navigationIcon = {
                        IconButton(onClick = { scope.launch { drawerState.open() } }) {
                            Icon(Icons.Default.Menu, contentDescription = "Menu", tint = Color.White)
                        }
                    },
                    actions = {
                        BadgedBox(
                            badge = {
                                if (state.notificationCount > 0) {
                                    Badge { Text(state.notificationCount.toString()) }
                                }
                            }
                        ) {
                            IconButton(onClick = onNavigateToNotifications) {
                                Icon(Icons.Default.Notifications, contentDescription = "Notifications", tint = Color.White)
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color(0xFF6A0DAD)
                    )
                )
            }
        ) { padding ->
            if (state.isLoading) {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Color(0xFF6A0DAD))
                }
            } else {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .verticalScroll(rememberScrollState()),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Spacer(modifier = Modifier.height(32.dp))

                    GreetingSection(displayName = state.displayName)

                    Spacer(modifier = Modifier.height(32.dp))

                    ActionButtons(
                        userRole = state.userRole,
                        onMySchedulesClick = onNavigateToMySchedules,
                        onNewScheduleClick = onNavigateToNewSchedule,
                        onArchivedClick = onNavigateToArchived,
                        onProfileClick = onNavigateToProfile
                    )

                    Spacer(modifier = Modifier.height(16.dp))
                }
            }
        }
    }
}

@Composable
private fun GreetingSection(displayName: String?) {
    val greeting = buildHomeGreeting(displayName)
    Text(
        text = greeting,
        fontSize = 25.sp,
        textAlign = TextAlign.Center,
        modifier = Modifier.padding(horizontal = 16.dp)
    )
}

@Composable
private fun ActionButtons(
    userRole: Role?,
    onMySchedulesClick: () -> Unit,
    onNewScheduleClick: () -> Unit,
    onArchivedClick: () -> Unit,
    onProfileClick: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Button(
            onClick = onMySchedulesClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Color(0xFF6A0DAD)
            ),
            shape = MaterialTheme.shapes.medium
        ) {
            Text("My Schedules", fontSize = 18.sp)
        }

        // Shown to any signed-in user, matching iOS (which is ungated). The Go API
        // enforces who may actually create (manager-only), so this is UI parity, not
        // an authz decision. NOTE: Android currently never populates userRole
        // (FirebaseAuthRepository.toDomainUser hardcodes role=null), so the previous
        // `userRole == Role.EMPLOYER` gate made this button dead for everyone.
        Button(
            onClick = onNewScheduleClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Color(0xFF6A0DAD)
            ),
            shape = MaterialTheme.shapes.medium
        ) {
            Text("Create New Schedule", fontSize = 18.sp)
        }

        Button(
            onClick = onArchivedClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Color(0xFF6A0DAD)
            ),
            shape = MaterialTheme.shapes.medium
        ) {
            Text("Archived Schedules", fontSize = 18.sp)
        }

        Button(
            onClick = onProfileClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(60.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = Color(0xFF6A0DAD)
            ),
            shape = MaterialTheme.shapes.medium
        ) {
            Text("Profile", fontSize = 18.sp)
        }
    }
}

@Composable
private fun DrawerContent(
    displayName: String?,
    userRole: Role?,
    isPremium: Boolean
) {
    Column(modifier = Modifier.padding(16.dp)) {
        Text(
            text = displayName ?: "User",
            style = MaterialTheme.typography.titleLarge
        )
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text = "Role: ${userRole?.name?.lowercase()?.capitalize() ?: "Unknown"}",
            style = MaterialTheme.typography.bodyMedium
        )
        if (isPremium) {
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = "Premium",
                style = MaterialTheme.typography.bodySmall,
                color = Color(0xFF6A0DAD)
            )
        }
    }
}

private fun buildHomeGreeting(displayName: String?): String {
    val hour = java.time.LocalTime.now().hour
    val timeGreeting = when {
        hour < 12 -> "Good morning"
        hour < 17 -> "Good afternoon"
        else -> "Good evening"
    }
    val name = displayName?.takeIf { it.isNotBlank() } ?: "there"
    return "$timeGreeting, $name!"
}
