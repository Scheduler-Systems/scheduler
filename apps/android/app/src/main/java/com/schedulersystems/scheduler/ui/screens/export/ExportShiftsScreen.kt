package com.schedulersystems.scheduler.ui.screens.export

import androidx.compose.foundation.layout.*
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
fun ExportShiftsScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: ExportShiftsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(scheduleId) {
        viewModel.loadSchedule(scheduleId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Export Shifts", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(24.dp)
            ) {
                Text(state.scheduleName, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFF6A0DAD))

                Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))) {
                    Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        Text("Google Calendar", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                        Text("Export the schedule shifts directly to a Google Calendar.", fontSize = 14.sp, color = Color.Gray)

                        Button(
                            onClick = { viewModel.exportToGoogleCalendar(scheduleId) },
                            modifier = Modifier.fillMaxWidth().height(50.dp),
                            enabled = !state.isExporting,
                            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                            shape = MaterialTheme.shapes.medium
                        ) {
                            if (state.isExporting) CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Color.White)
                            else Text("Export to Google Calendar", fontSize = 16.sp)
                        }
                    }
                }

                if (state.isExported) {
                    Text("Shifts exported successfully!", color = Color(0xFF4CAF50), fontSize = 14.sp, fontWeight = FontWeight.Medium)
                }
                state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp) }
            }
        }
    }
}
