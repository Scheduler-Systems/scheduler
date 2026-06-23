package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel

private val DAYS = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")
private val SHIFTS = listOf("Morning", "Afternoon", "Night")

/**
 * Schedule Build: a manager runs the shift-assignment algorithm for a schedule; the
 * resulting grid is persisted via the Go API (built-schedules endpoint) and rendered.
 * Replaces the previous direct-Firestore screen — the grid is now API-backed.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleBuildScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: ScheduleBuildViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsState()

    LaunchedEffect(scheduleId) { viewModel.load(scheduleId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Build Schedule") },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp)
                .verticalScroll(rememberScrollState())
        ) {
            Button(
                onClick = { viewModel.build(scheduleId) },
                enabled = !state.isLoading,
                modifier = Modifier.fillMaxWidth()
            ) {
                if (state.isLoading) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(20.dp).width(20.dp),
                        color = MaterialTheme.colorScheme.onPrimary
                    )
                } else {
                    Text("Build Schedule")
                }
            }

            Spacer(Modifier.height(16.dp))

            state.error?.let { err ->
                Text("Error: $err", color = MaterialTheme.colorScheme.error)
                Spacer(Modifier.height(16.dp))
            }

            if (state.grid.isEmpty()) {
                if (!state.isLoading) {
                    Text(
                        "No schedule built yet. Tap Build Schedule to generate one.",
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            } else {
                // grid is day-major: grid[day][shift] = the station name(s) for that slot.
                Text(
                    "Built Schedule",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth()) {
                    Text("Day", Modifier.width(44.dp), fontWeight = FontWeight.SemiBold)
                    SHIFTS.forEach { shift ->
                        Text(
                            shift,
                            Modifier.weight(1f),
                            fontWeight = FontWeight.SemiBold,
                            style = MaterialTheme.typography.bodySmall
                        )
                    }
                }
                state.grid.forEachIndexed { dayIndex, dayShifts ->
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .padding(vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Text(DAYS.getOrElse(dayIndex) { "?" }, Modifier.width(44.dp))
                        for (shiftIndex in SHIFTS.indices) {
                            val cell = dayShifts.getOrNull(shiftIndex).orEmpty()
                                .filter { it.isNotBlank() }.joinToString(", ")
                            Text(
                                cell.ifBlank { "—" },
                                Modifier.weight(1f),
                                style = MaterialTheme.typography.bodySmall
                            )
                        }
                    }
                }
            }
        }
    }
}
