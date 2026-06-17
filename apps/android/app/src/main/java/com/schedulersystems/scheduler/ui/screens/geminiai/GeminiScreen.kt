package com.schedulersystems.scheduler.ui.screens.geminiai

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
fun GeminiScreen(
    scheduleName: String? = null,
    onNavigateBack: () -> Unit,
    viewModel: GeminiViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("AI Scheduler", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
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
            modifier = Modifier.fillMaxSize().padding(padding).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            if (scheduleName != null) {
                Text("Schedule: $scheduleName", fontSize = 16.sp, color = Color.Gray)
            }

            Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))) {
                Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("Ask Gemini", fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
                    Text("Get AI-powered scheduling suggestions", fontSize = 14.sp, color = Color.Gray)

                    OutlinedTextField(
                        value = state.prompt,
                        onValueChange = { viewModel.setPrompt(it) },
                        placeholder = { Text("e.g., Optimize next week's schedule") },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 5
                    )

                    Button(
                        onClick = { viewModel.generate() },
                        modifier = Modifier.fillMaxWidth().height(50.dp),
                        enabled = !state.isLoading && state.prompt.isNotBlank(),
                        colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD)),
                        shape = MaterialTheme.shapes.medium
                    ) {
                        if (state.isLoading) CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Color.White)
                        else Text("Generate", fontSize = 16.sp)
                    }
                }
            }

            if (state.response.isNotEmpty()) {
                Card(
                    modifier = Modifier.fillMaxWidth(),
                    colors = CardDefaults.cardColors(containerColor = Color(0xFFE8F5E9))
                ) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text("Response", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(state.response, fontSize = 14.sp, lineHeight = 20.sp)
                    }
                }
            }

            state.error?.let { Text(it, color = Color.Red, fontSize = 14.sp) }
        }
    }
}
