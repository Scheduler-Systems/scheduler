package com.schedulersystems.scheduler.ui.screens.shift

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
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
import com.schedulersystems.scheduler.models.domain.ShiftRow

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShiftScreen(
    scheduleId: String,
    weekStart: String? = null,
    onNavigateBack: () -> Unit,
    viewModel: ShiftViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()

    LaunchedEffect(scheduleId) {
        viewModel.loadShifts(scheduleId, weekStart)
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Box(
                        modifier = Modifier.fillMaxWidth(),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = "Shifts",
                            fontSize = 22.sp,
                            fontWeight = FontWeight.Medium,
                            color = Color.White
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(
                            Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Back",
                            tint = Color.White
                        )
                    }
                },
                actions = {
                    Spacer(modifier = Modifier.width(48.dp))
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Color(0xFF6A0DAD)
                )
            )
        }
    ) { padding ->
        when {
            state.isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator(color = Color(0xFF6A0DAD))
                }
            }
            state.error != null -> {
                ErrorState(message = state.error ?: "Unknown error")
            }
            state.shiftRows.isEmpty() -> {
                EmptyShiftsContent()
            }
            else -> {
                ShiftList(
                    shiftRows = state.shiftRows,
                    modifier = Modifier.padding(padding)
                )
            }
        }
    }
}

@Composable
private fun EmptyShiftsContent() {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = "No shifts scheduled",
                fontSize = 18.sp,
                color = Color.Gray
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "Check back later for updates",
                fontSize = 14.sp,
                color = Color.Gray
            )
        }
    }
}

@Composable
private fun ShiftList(
    shiftRows: List<ShiftRow>,
    modifier: Modifier = Modifier
) {
    LazyColumn(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        items(shiftRows) { shiftRow ->
            ShiftRowCard(shiftRow = shiftRow)
        }
    }
}

@Composable
private fun ShiftRowCard(shiftRow: ShiftRow) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = Color(0xFFF5F5F5))
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            shiftRow.shifts.forEach { shift ->
                ShiftItem(shift = shift)
                if (shift != shiftRow.shifts.last()) {
                    Divider(
                        modifier = Modifier.padding(vertical = 8.dp),
                        color = Color.LightGray
                    )
                }
            }
        }
    }
}

@Composable
private fun ShiftItem(
    shift: com.schedulersystems.scheduler.models.domain.Shift
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column {
            Text(
                text = shift.day,
                fontSize = 16.sp,
                fontWeight = FontWeight.SemiBold
            )
            Text(
                text = "${shift.startTime} - ${shift.endTime}",
                fontSize = 14.sp,
                color = Color.Gray
            )
        }
        shift.assignedWorker?.let { worker ->
            AssistChip(
                onClick = {},
                label = {
                    Text(
                        text = worker,
                        fontSize = 12.sp,
                        maxLines = 1
                    )
                },
                colors = AssistChipDefaults.assistChipColors(
                    containerColor = Color(0xFFE8D4F8)
                )
            )
        } ?: run {
            AssistChip(
                onClick = {},
                label = {
                    Text(
                        text = "Unassigned",
                        fontSize = 12.sp
                    )
                },
                colors = AssistChipDefaults.assistChipColors(
                    containerColor = Color(0xFFFFE4E1)
                )
            )
        }
    }
}

@Composable
private fun ErrorState(message: String) {
    Box(
        modifier = Modifier.fillMaxSize(),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = message,
            fontSize = 16.sp,
            color = Color.Red
        )
    }
}
