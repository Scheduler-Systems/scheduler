package com.schedulersystems.scheduler.ui.screens.employees

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
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
import com.schedulersystems.scheduler.models.domain.Employee

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun EmployeeListScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit,
    viewModel: EmployeeListViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val addState by viewModel.addState.collectAsStateWithLifecycle()
    var showAddDialog by remember { mutableStateOf(false) }

    LaunchedEffect(scheduleId) {
        viewModel.loadEmployees(scheduleId)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text("Employees", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Color.White)
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = Color.White)
                    }
                },
                actions = {
                    IconButton(onClick = { showAddDialog = true }) {
                        Icon(Icons.Default.Add, contentDescription = "Add", tint = Color.White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color(0xFF6A0DAD))
            )
        }
    ) { padding ->
        Box(modifier = Modifier.fillMaxSize().padding(padding)) {
            when {
                state.isLoading -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(color = Color(0xFF6A0DAD))
                    }
                }
                state.employees.isEmpty() -> {
                    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Text("No employees added", fontSize = 16.sp, color = Color.Gray)
                    }
                }
                else -> {
                    Column(modifier = Modifier.fillMaxSize().padding(16.dp)) {
                        Text(state.scheduleName, fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Color(0xFF6A0DAD))
                        Spacer(modifier = Modifier.height(8.dp))
                        Text("${state.employees.size} employees", fontSize = 14.sp, color = Color.Gray)
                        Spacer(modifier = Modifier.height(16.dp))
                        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            items(state.employees, key = { it.id }) { employee ->
                                EmployeeRow(
                                    employee = employee,
                                    onRemove = { viewModel.removeEmployee(scheduleId, employee.id) }
                                )
                            }
                        }
                    }
                }
            }
        }
    }

    if (showAddDialog) {
        AlertDialog(
            onDismissRequest = { showAddDialog = false },
            title = { Text("Add Employee") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = addState.name,
                        onValueChange = { viewModel.setName(it) },
                        label = { Text("Name") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = addState.email,
                        onValueChange = { viewModel.setEmail(it) },
                        label = { Text("Email") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    OutlinedTextField(
                        value = addState.phone,
                        onValueChange = { viewModel.setPhone(it) },
                        label = { Text("Phone") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    addState.error?.let { Text(it, color = Color.Red, fontSize = 12.sp) }
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        viewModel.addEmployee(scheduleId)
                        if (addState.isAdded) showAddDialog = false
                    },
                    enabled = !addState.isAdding && addState.name.isNotBlank(),
                    colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF6A0DAD))
                ) {
                    Text("Add")
                }
            },
            dismissButton = {
                TextButton(onClick = { showAddDialog = false }) { Text("Cancel") }
            }
        )
    }
}

@Composable
private fun EmployeeRow(employee: Employee, onRemove: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(Color(0xFFF5F5F5), RoundedCornerShape(8.dp))
            .padding(12.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column {
            Text(employee.name, fontSize = 16.sp, fontWeight = FontWeight.Medium)
            employee.email?.let { Text(it, fontSize = 13.sp, color = Color.Gray) }
            employee.phone?.let { Text(it, fontSize = 13.sp, color = Color.Gray) }
        }
        IconButton(onClick = onRemove) {
            Icon(Icons.Default.Delete, contentDescription = "Remove", tint = Color.Red)
        }
    }
}
