package com.schedulersystems.scheduler.ui.screens.schedule

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FirebaseFirestore
import com.schedulersystems.scheduler.ui.theme.*
import kotlinx.coroutines.tasks.await
import java.text.SimpleDateFormat
import java.util.*

data class EmployeeEntry(
    val employeeName: String = "",
    val role: String = ""
)

data class ShiftSettings(
    val morning: Boolean = true,
    val afternoon: Boolean = true,
    val night: Boolean = true,
    val morningHours: String = "",
    val noonHours: String = "",
    val nightHours: String = ""
)

val EMPLOYEE_COLORS = listOf(
    Color(0xFF6A0DAD), Color(0xFF39D2C0), Color(0xFFE21C3D), Color(0xFF04A24C),
    Color(0xFFFF8C00), Color(0xFF1E90FF), Color(0xFF8B4513), Color(0xFFDC143C),
    Color(0xFF008080), Color(0xFF4B0082), Color(0xFFB8860B), Color(0xFF2F4F4F),
    Color(0xFF800000), Color(0xFF556B2F), Color(0xFFDAA520), Color(0xFF7B68EE),
    Color(0xFF3CB371), Color(0xFFCD853F), Color(0xFF4682B4), Color(0xFF9ACD32)
)

val DAY_NAMES = listOf("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")

fun getEmployeeColor(name: String): Color {
    var hash = 0
    for (c in name) hash = c.code + ((hash shl 5) - hash)
    return EMPLOYEE_COLORS[kotlin.math.abs(hash) % EMPLOYEE_COLORS.size]
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScheduleBuildScreen(
    scheduleId: String,
    onNavigateBack: () -> Unit
) {
    val db = FirebaseFirestore.getInstance()
    val scheduleRef = db.document("schedules/$scheduleId")

    var scheduleBuildList by remember { mutableStateOf<List<List<String>>>(emptyList()) }
    var settings by remember { mutableStateOf<ShiftSettings?>(null) }
    var employees by remember { mutableStateOf<List<EmployeeEntry>>(emptyList()) }
    var selectedEmployee by remember { mutableStateOf<EmployeeEntry?>(null) }
    var weekDates by remember { mutableStateOf<List<Date>>(emptyList()) }
    var isLoading by remember { mutableStateOf(true) }
    var scheduleName by remember { mutableStateOf("") }

    LaunchedEffect(scheduleId) {
        try {
            val doc = scheduleRef.get().await()
            val data = doc.data ?: emptyMap()
            scheduleName = data["schedule_name"] as? String ?: "Schedule"

            val settingsData = data["schedule_settings"] as? Map<String, Any>
            val shiftsData = settingsData?.get("enabledShifts") as? Map<String, Any>
            settings = ShiftSettings(
                morning = shiftsData?.get("morning") as? Boolean ?: true,
                afternoon = shiftsData?.get("afternoon") as? Boolean ?: true,
                night = shiftsData?.get("night") as? Boolean ?: true,
                morningHours = shiftsData?.get("morningHours") as? String ?: "",
                noonHours = shiftsData?.get("noonHours") as? String ?: "",
                nightHours = shiftsData?.get("nightHours") as? String ?: ""
            )

            val empData = data["employees"] as? List<Map<String, Any>>
            employees = empData?.mapNotNull { emp ->
                val name = emp["employee_name"] as? String ?: return@mapNotNull null
                val roleData = emp["role"] as? Map<String, Boolean>
                val role = when {
                    roleData?.get("is_admin") == true -> "Admin"
                    roleData?.get("is_creator") == true -> "Creator"
                    else -> "Worker"
                }
                EmployeeEntry(employeeName = name, role = role)
            } ?: emptyList()

            val stations = (data["stations_count"] as? Long)?.toInt() ?: 3
            scheduleBuildList = List(stations) { List(21) { "" } }

            val today = Date()
            val cal = Calendar.getInstance()
            cal.time = today
            cal.firstDayOfWeek = Calendar.SUNDAY
            val dayOfWeek = cal.get(Calendar.DAY_OF_WEEK) - 1
            cal.add(Calendar.DAY_OF_MONTH, -dayOfWeek)
            weekDates = (0..6).map { offset ->
                cal.time.also { cal.add(Calendar.DAY_OF_MONTH, 1) }
            }

            isLoading = false
        } catch (_: Exception) {
            isLoading = false
        }
    }

    val dateFormat = SimpleDateFormat("d/M/y", Locale.getDefault())
    val firstWeek = weekDates.firstOrNull()?.let { dateFormat.format(it) } ?: ""
    val lastWeek = weekDates.lastOrNull()?.let { dateFormat.format(it) } ?: ""

    Surface(color = SchedulerPrimary) {
        TopAppBar(
            title = { Column { Text(scheduleName, color = Color.White); Text("Schedule Builder", color = Color.White.copy(0.7f), fontSize = 12.sp) } },
            navigationIcon = { IconButton(onClick = onNavigateBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, null, tint = Color.White) } },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = SchedulerPrimary)
        )
    }

    Box(Modifier.fillMaxSize().background(SchedulerPrimaryBackground)) {
        if (isLoading) {
            CircularProgressIndicator(Modifier.align(Alignment.Center), color = SchedulerPrimary)
        } else {
            Column(Modifier.verticalScroll(rememberScrollState()).padding(12.dp)) {
                Text("$firstWeek - $lastWeek", Modifier.fillMaxWidth(), textAlign = TextAlign.Center,
                    color = SchedulerPrimaryText, fontSize = 14.sp)

                scheduleBuildList.forEachIndexed { stationIndex, stationData ->
                    Text("Station ${stationIndex + 1}", Modifier.padding(top = 16.dp, bottom = 8.dp),
                        fontWeight = FontWeight.Medium, fontSize = 14.sp, color = SchedulerPrimaryText)

                    Column {
                        // Header row
                        Row(Modifier.fillMaxWidth()) {
                            Box(Modifier.weight(1f).height(48.dp).padding(2.dp)
                                .clip(RoundedCornerShape(8.dp)).background(SchedulerSecondaryBackground),
                                contentAlignment = Alignment.Center) {
                                Text("Day", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = SchedulerPrimaryText)
                            }
                            ShiftHeaderCell("Morning", settings?.morningHours ?: "", settings?.morning ?: true, Modifier.weight(1f))
                            ShiftHeaderCell("Afternoon", settings?.noonHours ?: "", settings?.afternoon ?: true, Modifier.weight(1f))
                            ShiftHeaderCell("Night", settings?.nightHours ?: "", settings?.night ?: true, Modifier.weight(1f))
                        }

                        // Day rows
                        DAY_NAMES.forEachIndexed { dayIndex, dayName ->
                            val date = weekDates.getOrNull(dayIndex)
                            val dateStr = date?.let { dateFormat.format(it) } ?: ""

                            Row(Modifier.fillMaxWidth()) {
                                Box(Modifier.weight(1f).height(64.dp).padding(2.dp)
                                    .clip(RoundedCornerShape(8.dp)).background(SchedulerSecondaryBackground),
                                    contentAlignment = Alignment.Center) {
                                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                        Text(dayName, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = SchedulerPrimaryText)
                                        Text(dateStr, fontSize = 9.sp, color = SchedulerSecondaryText)
                                    }
                                }
                                ShiftCell(stationData.getOrElse(dayIndex * 3) { "" }, settings?.morning ?: true, employees, Modifier.weight(1f)) { selectedEmployee = it }
                                ShiftCell(stationData.getOrElse(dayIndex * 3 + 1) { "" }, settings?.afternoon ?: true, employees, Modifier.weight(1f)) { selectedEmployee = it }
                                ShiftCell(stationData.getOrElse(dayIndex * 3 + 2) { "" }, settings?.night ?: true, employees, Modifier.weight(1f)) { selectedEmployee = it }
                            }
                        }
                    }
                }
            }
        }
    }

    selectedEmployee?.let { emp ->
        Dialog(onDismissRequest = { selectedEmployee = null }) {
            Card(shape = RoundedCornerShape(12.dp), colors = CardDefaults.cardColors(containerColor = Color.White)) {
                Column(Modifier.padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(emp.employeeName, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                    Text("Role: ${emp.role}", color = SchedulerSecondaryText, modifier = Modifier.padding(top = 4.dp))
                    Spacer(Modifier.height(16.dp))
                    Button(
                        onClick = { selectedEmployee = null },
                        Modifier.fillMaxWidth(),
                        colors = ButtonDefaults.buttonColors(containerColor = SchedulerPrimary)
                    ) { Text("Close") }
                }
            }
        }
    }
}

@Composable
fun ShiftHeaderCell(title: String, hours: String, enabled: Boolean, modifier: Modifier) {
    Box(
        modifier.height(48.dp).padding(2.dp).clip(RoundedCornerShape(8.dp))
            .background(if (enabled) SchedulerSecondaryBackground else SchedulerLineColor),
        contentAlignment = Alignment.Center
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
                color = if (enabled) SchedulerPrimaryText else Color.White)
            if (enabled && hours.isNotEmpty()) {
                Text(hours, fontSize = 8.sp, color = SchedulerSecondaryText)
            }
        }
    }
}

@Composable
fun ShiftCell(
    name: String,
    enabled: Boolean,
    employees: List<EmployeeEntry>,
    modifier: Modifier,
    onSelect: (EmployeeEntry) -> Unit
) {
    val color = when {
        !enabled -> SchedulerLineColor
        name.isBlank() -> SchedulerSecondaryBackground
        else -> getEmployeeColor(name)
    }

    Box(
        modifier.height(64.dp).padding(2.dp).clip(RoundedCornerShape(8.dp))
            .background(color)
            .then(if (name.isNotBlank()) Modifier.clickable { employees.find { it.employeeName == name }?.let { onSelect(it) } } else Modifier),
        contentAlignment = Alignment.Center
    ) {
        if (name.isNotBlank()) {
            Text(name, color = Color.White, fontSize = 9.sp, fontWeight = FontWeight.Medium,
                textAlign = TextAlign.Center, lineHeight = 12.sp,
                modifier = Modifier.padding(2.dp))
        }
    }
}
