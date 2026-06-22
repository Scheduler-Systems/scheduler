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

// Auth onboarding step 1: enter display name → PUT /users/{uid} → continue to choose-role.
@Composable
fun GetNameScreen(
    onNavigateToChooseRole: () -> Unit,
    onNavigateBack: () -> Unit,
    viewModel: GetNameViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var name by remember { mutableStateOf("") }

    LaunchedEffect(state.isSaved) {
        if (state.isSaved) onNavigateToChooseRole()
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("What's your name?", fontSize = 24.sp, fontWeight = FontWeight.Medium)
        Spacer(modifier = Modifier.height(24.dp))
        OutlinedTextField(
            value = name,
            onValueChange = { name = it },
            label = { Text("Your name") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth()
        )
        Spacer(modifier = Modifier.height(8.dp))
        state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp) }
        Spacer(modifier = Modifier.height(16.dp))
        Button(
            onClick = { viewModel.saveName(name) },
            enabled = name.isNotBlank() && !state.isSaving,
            modifier = Modifier.fillMaxWidth().height(50.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD))
        ) {
            Text(if (state.isSaving) "Saving…" else "Continue", fontSize = 16.sp)
        }
        Spacer(modifier = Modifier.height(12.dp))
        TextButton(onClick = onNavigateBack) { Text("Back") }
    }
}
