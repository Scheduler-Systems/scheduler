package com.schedulersystems.scheduler.ui.screens.auth

import androidx.compose.foundation.layout.*
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

// Auth onboarding step 2: pick role → PUT /users/{uid}/role → go home.
@Composable
fun ChooseRoleScreen(
    onNavigateToHome: () -> Unit,
    onNavigateBack: () -> Unit,
    viewModel: ChooseRoleViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(state.isSaved) {
        if (state.isSaved) onNavigateToHome()
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("Choose Your Role", fontSize = 24.sp, fontWeight = FontWeight.Bold)
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            "Choose your role, so that we personalize your experience",
            fontSize = 14.sp, color = Color.Gray
        )
        Spacer(modifier = Modifier.height(24.dp))
        state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp); Spacer(modifier = Modifier.height(8.dp)) }
        Button(
            onClick = { viewModel.saveRole(true) },
            enabled = !state.isSaving,
            modifier = Modifier.fillMaxWidth().height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD))
        ) {
            Text(if (state.isSaving) "Saving…" else "Log In as Manager", fontSize = 16.sp)
        }
        Spacer(modifier = Modifier.height(12.dp))
        Button(
            onClick = { viewModel.saveRole(false) },
            enabled = !state.isSaving,
            modifier = Modifier.fillMaxWidth().height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFE91E63))
        ) {
            Text(if (state.isSaving) "Saving…" else "Log In as Employee", fontSize = 16.sp)
        }
        Spacer(modifier = Modifier.height(12.dp))
        TextButton(onClick = onNavigateBack) { Text("Back") }
    }
}
