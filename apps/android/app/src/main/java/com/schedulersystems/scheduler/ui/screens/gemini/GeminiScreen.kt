package com.schedulersystems.scheduler.ui.screens.gemini

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.schedulersystems.scheduler.ui.components.SchedulerButton

@Composable
fun GeminiScreen(
    scheduleName: String?,
    onNavigateBack: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("Gemini Assistant", style = MaterialTheme.typography.headlineMedium)
        if (scheduleName != null) {
            Text("Schedule: $scheduleName", style = MaterialTheme.typography.bodyMedium)
        }
        Spacer(modifier = Modifier.height(24.dp))
        SchedulerButton(text = "Back", onClick = onNavigateBack)
    }
}
