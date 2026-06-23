package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.schedulersystems.scheduler.models.domain.Schedule
import com.schedulersystems.scheduler.models.domain.Role
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleDetailScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    onNavigateToEmployeeList: () -> Unit = {},
    onNavigateToSettings: () -> Unit = {},
    onNavigateToRequests: () -> Unit = {},
    onNavigateToPriorities: () -> Unit = {},
    onNavigateToCurrentPriorities: () -> Unit = {},
    onNavigateToBuild: () -> Unit = {},
    onNavigateToSharePdf: () -> Unit = {},
    onNavigateToExport: () -> Unit = {},
    viewModel: ScheduleDetailViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()
    val drawerState = rememberDrawerState(initialValue = DrawerValue.Closed)

    LaunchedEffect(scheduleId) {
        viewModel.loadSchedule(scheduleId)
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            ModalDrawerSheet {
                DrawerMenuContent()
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
                                text = state.schedule?.name ?: "Schedule",
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
                        IconButton(onClick = onNavigateBack) {
                            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(
                        containerColor = Color(0xFF6A0DAD)
                    )
                )
            }
        ) { padding ->
            when {
                state.isLoading -> {
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(padding),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator(color = Color(0xFF6A0DAD))
                    }
                }
                state.error != null -> {
                    ErrorContent(
                        message = state.error ?: "Unknown error",
                        onRetry = { viewModel.loadSchedule(scheduleId) }
                    )
                }
                state.schedule != null -> {
                    ScheduleDetailContent(
                        schedule = state.schedule!!,
                        userRole = state.userRole,
                        onEmployeeListClick = onNavigateToEmployeeList,
                        onPrioritiesClick = onNavigateToPriorities,
                        onCurrentPrioritiesClick = onNavigateToCurrentPriorities,
                        onBuildClick = onNavigateToBuild,
                        onSharePdfClick = onNavigateToSharePdf,
                        onExportClick = onNavigateToExport,
                        onSettingsClick = onNavigateToSettings,
                        onRequestsClick = onNavigateToRequests,
                        modifier = Modifier.padding(padding)
                    )
                }
            }
        }
    }
}

@Composable
private fun ScheduleDetailContent(
    schedule: Schedule,
    userRole: Role?,
    onEmployeeListClick: () -> Unit,
    onPrioritiesClick: () -> Unit,
    onCurrentPrioritiesClick: () -> Unit,
    onBuildClick: () -> Unit,
    onSharePdfClick: () -> Unit,
    onExportClick: () -> Unit,
    onSettingsClick: () -> Unit,
    onRequestsClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(24.dp)
    ) {
        ScheduleNameHeader(schedule.name)

        StatisticsSection(
            employeeCount = schedule.employees.size,
            nextScheduleCount = schedule.nextSchedule.size
        )

        ActionButtonsSection(
            userRole = userRole,
            onEmployeeListClick = onEmployeeListClick,
            onPrioritiesClick = onPrioritiesClick,
            onCurrentPrioritiesClick = onCurrentPrioritiesClick,
            onBuildClick = onBuildClick,
            onSharePdfClick = onSharePdfClick,
            onExportClick = onExportClick,
            onSettingsClick = onSettingsClick,
            onRequestsClick = onRequestsClick
        )
    }
}

@Composable
private fun ScheduleNameHeader(name: String) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        Text(
            text = "Schedule Name:",
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold
        )
        Text(
            text = name,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold
        )
    }
}

@Composable
private fun StatisticsSection(
    employeeCount: Int,
    nextScheduleCount: Int
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Statistics",
                fontSize = 18.sp,
                fontWeight = FontWeight.SemiBold
            )
            Spacer(modifier = Modifier.height(12.dp))
            StatRow(label = "Employees", value = employeeCount.toString())
            StatRow(label = "Built Schedules", value = nextScheduleCount.toString())
        }
    }
}

@Composable
private fun StatRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(text = label, fontSize = 14.sp, color = Color.Gray)
        Text(text = value, fontSize = 14.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun ActionButtonsSection(
    userRole: Role?,
    onEmployeeListClick: () -> Unit,
    onPrioritiesClick: () -> Unit,
    onCurrentPrioritiesClick: () -> Unit,
    onBuildClick: () -> Unit,
    onSharePdfClick: () -> Unit,
    onExportClick: () -> Unit,
    onSettingsClick: () -> Unit,
    onRequestsClick: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(
            onClick = onRequestsClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Schedule Requests", fontSize = 16.sp)
        }

        Button(
            onClick = onEmployeeListClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Employee List & Add Requests", fontSize = 16.sp)
        }

        Button(
            onClick = onSettingsClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Schedule Settings", fontSize = 16.sp)
        }

        Button(
            onClick = onPrioritiesClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Submit Priorities", fontSize = 16.sp)
        }

        Button(
            onClick = onCurrentPrioritiesClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Current Priorities", fontSize = 16.sp)
        }

        // Ungated (matches iOS): the Android auth repo always maps role=null, so an
        // EMPLOYER check would hide this for everyone; the server enforces manager-only
        // on POST /built-schedules.
        Button(
            onClick = onBuildClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Build Schedule", fontSize = 16.sp)
        }

        Button(
            onClick = onSharePdfClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Share PDF", fontSize = 16.sp)
        }

        Button(
            onClick = onExportClick,
            modifier = Modifier
                .fillMaxWidth()
                .height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
            shape = MaterialTheme.shapes.small
        ) {
            Text("Export Shifts", fontSize = 16.sp)
        }
    }
}

@Composable
private fun ErrorContent(
    message: String,
    onRetry: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = message,
            fontSize = 16.sp,
            color = Color.Red
        )
        Spacer(modifier = Modifier.height(16.dp))
        Button(
            onClick = onRetry,
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD))
        ) {
            Text("Retry")
        }
    }
}

@Composable
private fun DrawerMenuContent() {
    Column(modifier = Modifier.padding(16.dp)) {
        Text("Menu", style = MaterialTheme.typography.titleLarge)
    }
}
