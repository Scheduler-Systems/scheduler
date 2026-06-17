package com.schedulersystems.scheduler.ui.screens.priorities

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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrioritiesSubmissionScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: PrioritiesViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(scheduleId) {
        viewModel.loadPriorities(scheduleId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Submit Priorities", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
        } else if (state.priorities.isEmpty()) {
            Box(modifier = Modifier.fillMaxSize().padding(padding), contentAlignment = Alignment.Center) {
                Text("No priorities configured", fontSize = 16.sp, color = Color.Gray)
            }
        } else {
            Column(
                modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                Text("Priority Order", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFF6A0DAD))

                LazyColumn(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    itemsIndexed(state.priorities) { index, employee ->
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Text("${index + 1}. $employee", fontSize = 16.sp)
                            Checkbox(
                                checked = state.submittedPriorities.getOrElse(index) { false },
                                onCheckedChange = { viewModel.togglePriority(index) },
                                colors = CheckboxDefaults.colors(checkedColor = Color(0xFF6A0DAD))
                            )
                        }
                    }
                }

                if (state.isSubmitted) {
                    Text("Priorities submitted!", color = Color(0xFF4CAF50), fontSize = 14.sp, fontWeight = FontWeight.Medium)
                }

                state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp) }

                Button(
                    onClick = { viewModel.submitPriorities(scheduleId) },
                    modifier = Modifier.fillMaxWidth().height(50.dp),
                    enabled = !state.isSubmitting,
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                    shape = MaterialTheme.shapes.medium
                ) {
                    if (state.isSubmitting) CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Color.White)
                    else Text("Submit", fontSize = 16.sp)
                }
            }
        }
    }
}
