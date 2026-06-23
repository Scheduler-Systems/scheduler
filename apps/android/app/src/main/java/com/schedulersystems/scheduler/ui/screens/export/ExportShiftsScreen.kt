package com.schedulersystems.scheduler.ui.screens.export

import android.content.Context
import android.content.Intent
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.hilt.navigation.compose.hiltViewModel
import java.io.File

private val DAYS = listOf("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

/**
 * Export Shifts: previews the built schedule, exports it to a real iCalendar (.ics) file, and
 * shares it via the system share sheet (imports into Google Calendar + any calendar app).
 * Replaces the previous Google-Calendar-OAuth stub — the .ics is real, credential-free.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExportShiftsScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: ExportShiftsViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsState()
    val context = LocalContext.current

    LaunchedEffect(scheduleId) { viewModel.load(scheduleId) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Export Shifts") },
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
            if (state.isLoading) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(Modifier.height(20.dp).width(20.dp))
                    Spacer(Modifier.width(12.dp))
                    Text("Preparing schedule…")
                }
            } else {
                Text(
                    "${state.scheduleName.ifBlank { "Untitled" }} Schedule",
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold
                )
                Spacer(Modifier.height(12.dp))

                state.error?.let { err ->
                    Text("Error: $err", color = MaterialTheme.colorScheme.error)
                    Spacer(Modifier.height(12.dp))
                }

                if (state.grid.isEmpty()) {
                    Text("No schedule built yet.", color = MaterialTheme.colorScheme.onSurfaceVariant)
                } else {
                    Text("Preview", fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(4.dp))
                    state.grid.forEachIndexed { dayIndex, dayShifts ->
                        val assigned = dayShifts.flatten().filter { it.isNotBlank() }.distinct().joinToString(", ")
                        if (assigned.isNotBlank()) {
                            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                                Text(DAYS.getOrElse(dayIndex) { "?" }, Modifier.width(44.dp), fontWeight = FontWeight.Medium)
                                Text(assigned, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }

                Spacer(Modifier.height(20.dp))

                Button(
                    onClick = { viewModel.export() },
                    enabled = !state.isExporting && state.grid.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth()
                ) {
                    if (state.isExporting) {
                        CircularProgressIndicator(
                            modifier = Modifier.height(20.dp).width(20.dp),
                            color = MaterialTheme.colorScheme.onPrimary
                        )
                    } else {
                        Text("Export to Calendar")
                    }
                }

                state.icsFile?.let { file ->
                    Spacer(Modifier.height(16.dp))
                    Text(
                        "Calendar file ready · ${state.eventCount} event(s)",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = { shareIcs(context, file) },
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Text("Share")
                    }
                }
            }
        }
    }
}

/** Fires the system share sheet for the generated .ics via a FileProvider URI. */
private fun shareIcs(context: Context, file: File) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    val intent = Intent(Intent.ACTION_SEND).apply {
        type = "text/calendar"
        putExtra(Intent.EXTRA_STREAM, uri)
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(intent, "Export Shifts"))
}
