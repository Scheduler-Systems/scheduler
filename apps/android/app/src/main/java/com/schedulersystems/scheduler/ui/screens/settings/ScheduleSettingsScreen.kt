package com.schedulersystems.scheduler.ui.screens.settings

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleSettingsScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: ScheduleSettingsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(scheduleId) {
        viewModel.loadSettings(scheduleId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Schedule Settings", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFF6A0DAD))
            )
        }
    ) { padding ->
        if (state.isLoading) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Color(0xFF6A0DAD))
            }
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(padding)
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(24.dp)
            ) {
                Text("Schedule Name: ${state.scheduleName}", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)

                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Enabled Shifts", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)

                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Morning", modifier = Modifier.padding(start = 4.dp))
                            Switch(
                                checked = state.enabledShifts.mornings,
                                onCheckedChange = { viewModel.toggleMorning(it) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF6A0DAD))
                            )
                        }
                        Divider()
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Afternoon", modifier = Modifier.padding(start = 4.dp))
                            Switch(
                                checked = state.enabledShifts.afternoons,
                                onCheckedChange = { viewModel.toggleAfternoon(it) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF6A0DAD))
                            )
                        }
                        Divider()
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Evening", modifier = Modifier.padding(start = 4.dp))
                            Switch(
                                checked = state.enabledShifts.evenings,
                                onCheckedChange = { viewModel.toggleEvening(it) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF6A0DAD))
                            )
                        }
                    }
                }

                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Submission Deadline", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Enable Deadline")
                            Switch(
                                checked = state.submissionDeadlineEnabled,
                                onCheckedChange = { viewModel.toggleDeadline(it) },
                                colors = SwitchDefaults.colors(checkedThumbColor = Color(0xFF6A0DAD))
                            )
                        }
                        if (state.submissionDeadlineEnabled) {
                            Text("Deadline Day: ${state.deadlineDay}", fontSize = 14.sp)
                        }
                    }
                }

                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Timezone", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                        Text("Current: ${state.timezone}", fontSize = 14.sp)
                    }
                }

                state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp) }

                if (state.isSaved) {
                    Text("Settings saved successfully!", color = Color(0xFF4CAF50), fontSize = 14.sp, fontWeight = FontWeight.Medium)
                }

                Button(
                    onClick = { viewModel.saveSettings(scheduleId) },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    enabled = !state.isSaving,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                    shape = MaterialTheme.shapes.medium
                ) {
                    if (state.isSaving) CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Color.White)
                    else Text("Save Settings", fontSize = 16.sp)
                }
            }
        }
    }
}
