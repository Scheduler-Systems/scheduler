package com.schedulersystems.scheduler.ui.screens.schedule

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
fun NewScheduleScreen(
    onNavigateBack: () -> Unit,
    onCreated: () -> Unit,
    viewModel: NewScheduleViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    // Navigate away once the schedule is persisted.
    LaunchedEffect(state.created) {
        if (state.created) onCreated()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("New Schedule", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            OutlinedTextField(
                value = state.name,
                onValueChange = { viewModel.setName(it) },
                label = { Text("Schedule Name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth()
            )
            state.error?.let { Text(it, color = Color.Red, fontSize = 13.sp) }
            Button(
                onClick = { viewModel.create() },
                enabled = !state.isCreating && state.name.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (state.isCreating) "Creating…" else "Create Schedule", fontSize = 16.sp)
            }
        }
    }
}
