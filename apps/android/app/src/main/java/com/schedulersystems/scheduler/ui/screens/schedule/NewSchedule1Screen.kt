package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.schedulersystems.scheduler.ui.components.SchedulerButton

@Composable
fun NewSchedule1Screen(
    onNavigateBack: () -> Unit,
    onNavigateToNewSchedule2: (String) -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("New Schedule", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(24.dp))
        SchedulerButton(
            text = "Continue",
            onClick = { onNavigateToNewSchedule2("My Schedule") }
        )
        Spacer(modifier = Modifier.height(12.dp))
        SchedulerButton(text = "Back", onClick = onNavigateBack)
    }
}
