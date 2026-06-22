package com.schedulersystems.scheduler.ui.screens.priority

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
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

// Read-only standings: lists the schedule's current priority order (current_priorities
// from the Go API). Reached from the schedule dashboard's "Current Priorities" button.
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CurrentPrioritiesScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: CurrentPrioritiesViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(scheduleId) {
        viewModel.loadCurrentPriorities(scheduleId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Current Priorities", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
        when {
            state.isLoading -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = Color(0xFF6A0DAD))
            }
            state.error != null -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text(state.error ?: "", color = Color.Red, fontSize = 16.sp)
            }
            state.priorities.isEmpty() -> Box(Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No priorities configured", fontSize = 16.sp, color = Color.Gray)
            }
            else -> Column(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Text("Priority Standings", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFF6A0DAD))
                LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    itemsIndexed(state.priorities) { index, name ->
                        Text("${index + 1}. $name", fontSize = 16.sp)
                    }
                }
            }
        }
    }
}
