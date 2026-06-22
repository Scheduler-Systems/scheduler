package com.schedulersystems.scheduler.ui.screens.requests

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
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
fun ScheduleRequestsScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: ScheduleRequestsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(scheduleId) { viewModel.load(scheduleId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Requests", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when {
                state.isLoading -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                    CircularProgressIndicator(color = Color(0xFF6A0DAD))
                }
                state.requests.isEmpty() -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                    Text("No requests", fontSize = 16.sp, color = Color.Gray)
                }
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize().padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    items(state.requests, key = { it.id }) { req ->
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .background(Color(0xFFF5F5F5), RoundedCornerShape(8.dp))
                                .padding(12.dp)
                        ) {
                            Text(req.toUserIdentification, fontSize = 16.sp, fontWeight = FontWeight.Medium)
                            Text(statusLabel(req.requestStatus), fontSize = 13.sp, color = Color(0xFFFF9800))
                        }
                    }
                }
            }
        }
    }
}

private fun statusLabel(status: com.schedulersystems.scheduler.models.domain.RequestStatus): String = when {
    status.name.endsWith("PENDING") -> "Pending"
    status == com.schedulersystems.scheduler.models.domain.RequestStatus.APPROVED -> "Approved"
    status == com.schedulersystems.scheduler.models.domain.RequestStatus.DECLINED -> "Declined"
    else -> status.name
}
