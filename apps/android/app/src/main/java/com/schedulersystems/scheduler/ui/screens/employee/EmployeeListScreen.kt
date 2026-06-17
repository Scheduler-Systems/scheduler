package com.schedulersystems.scheduler.ui.screens.employee

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.schedulersystems.scheduler.ui.components.SchedulerButton

@Composable
fun EmployeeListScreen(
    scheduleName: String,
    onNavigateBack: () -> Unit,
    onNavigateToAddEmployee: () -> Unit
) {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("Employees for $scheduleName", style = MaterialTheme.typography.headlineMedium)
        Spacer(modifier = Modifier.height(24.dp))
        SchedulerButton(text = "Add Employee", onClick = onNavigateToAddEmployee)
        Spacer(modifier = Modifier.height(12.dp))
        SchedulerButton(text = "Back", onClick = onNavigateBack)
    }
}
