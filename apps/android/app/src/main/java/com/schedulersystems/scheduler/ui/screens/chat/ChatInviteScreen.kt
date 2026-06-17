package com.schedulersystems.scheduler.ui.screens.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.firebase.Timestamp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.schedulersystems.scheduler.ui.theme.*
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import kotlin.random.Random

data class InviteUser(
    val uid: String = "",
    val displayName: String = "",
    val photoUrl: String = "",
    val phoneNumber: String = "",
    val email: String = "",
    val isAvailable: Boolean = true
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatInviteScreen(
    onNavigateBack: () -> Unit
) {
    val db = FirebaseFirestore.getInstance()
    val currentUserUid = FirebaseAuth.getInstance().currentUser?.uid ?: ""
    val scope = rememberCoroutineScope()

    var allUsers by remember { mutableStateOf<List<InviteUser>>(emptyList()) }
    var displayUsers by remember { mutableStateOf<List<InviteUser>>(emptyList()) }
    var selectedRefs by remember { mutableStateOf<List<DocumentReference>>(emptyList()) }
    var searchText by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(true) }
    var isSubmitting by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) {
        try {
            val snapshot = db.collection("users").orderBy("display_name").get().await()
            val users = snapshot.documents.mapNotNull { doc ->
                if (doc.id == currentUserUid) null
                else InviteUser(
                    uid = doc.id,
                    displayName = doc.getString("display_name") ?: "",
                    photoUrl = doc.getString("photo_url") ?: "",
                    phoneNumber = doc.getString("phone_number") ?: "",
                    email = doc.getString("email") ?: "",
                    isAvailable = doc.getBoolean("is_available") ?: true
                )
            }
            allUsers = users
            displayUsers = users.filter { it.isAvailable }
            isLoading = false
        } catch (_: Exception) { isLoading = false }
    }

    LaunchedEffect(searchText) {
        delay(300)
        val query = searchText.trim().lowercase()
        if (query.isEmpty()) {
            displayUsers = allUsers.filter { it.isAvailable }
            return@LaunchedEffect
        }
        val isNumeric = query.matches(Regex("^\\+?\\d+$"))
        val searchQuery = if (isNumeric && !query.startsWith("+")) "+$query" else query
        val results = allUsers.filter { u ->
            u.displayName.lowercase().contains(searchQuery) ||
            u.phoneNumber.lowercase().contains(searchQuery) ||
            u.email.lowercase().contains(searchQuery)
        }.take(5)
        displayUsers = if (results.isNotEmpty()) results else allUsers
    }

    val toggleUser: (DocumentReference) -> Unit = { ref ->
        selectedRefs = if (selectedRefs.any { it.path == ref.path }) {
            selectedRefs.filter { it.path != ref.path }
        } else {
            selectedRefs + ref
        }
    }

    val submit: () -> Unit = {
        if (selectedRefs.isNotEmpty()) {
        isSubmitting = true
        scope.launch {
            try {
                val currentRef = db.document("users/$currentUserUid")
                val allRefs = listOf(currentRef) + selectedRefs

                val existingSnap = db.collection("chats")
                    .whereArrayContains("users", currentRef).get().await()
                var found: DocumentReference? = null
                val wantedPaths = allRefs.map { it.path }.toSet()
                for (doc in existingSnap.documents) {
                    val chatPaths = (doc.get("users") as? List<*>)?.mapNotNull {
                        (it as? DocumentReference)?.path
                    }?.toSet() ?: continue
                    if (chatPaths == wantedPaths) { found = doc.reference; break }
                }

                if (found != null) {
                    onNavigateBack()
                } else {
                    val chatRef = db.collection("chats").document()
                    val groupId = Random.nextInt(1000000, 9999999)
                    chatRef.set(mapOf(
                        "users" to allRefs,
                        "user_a" to currentRef,
                        "user_b" to (selectedRefs.getOrNull(0) ?: currentRef),
                        "last_message" to "",
                        "last_message_time" to FieldValue.serverTimestamp(),
                        "last_message_sent_by" to currentRef,
                        "last_message_seen_by" to listOf(currentRef),
                        "group_chat_id" to groupId,
                        "schedule_ref" to null
                    )).await()
                    onNavigateBack()
                }
            } catch (_: Exception) {}
            isSubmitting = false
        }
    }
    }

    Box(Modifier.fillMaxSize().background(SchedulerPrimaryBackground)) {
        Column {
            Surface(color = SchedulerPrimary) {
                Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Invite/Remove Users", color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = 18.sp)
                            Text("Select users from below to start a chat", color = Color.White.copy(alpha = 0.8f), fontSize = 12.sp)
                        }
                        IconButton(onClick = onNavigateBack) {
                            Icon(Icons.Default.Close, "Close", tint = Color.White, modifier = Modifier.size(28.dp))
                        }
                    }
                }
            }

            OutlinedTextField(
                value = searchText, onValueChange = { searchText = it },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                placeholder = { Text("Search users") },
                shape = RoundedCornerShape(8.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = SchedulerPrimary,
                    unfocusedBorderColor = SchedulerPrimary
                )
            )

            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                Text("Invite Users", fontSize = 12.sp, color = SchedulerSecondaryText)
                Spacer(Modifier.weight(1f))
                Text("${selectedRefs.size}", fontSize = 14.sp, color = SchedulerPrimaryText)
                Text(" Selected", fontSize = 14.sp, color = SchedulerPrimaryText)
            }

            if (isLoading) {
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = SchedulerPrimary)
                }
            } else if (displayUsers.isEmpty()) {
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("No Users", style = MaterialTheme.typography.titleMedium, color = SchedulerPrimaryText)
                        Text("No users exist to create a chat with.", color = SchedulerSecondaryText)
                    }
                }
            } else {
                LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp)) {
                    items(displayUsers) { user ->
                        val ref = db.document("users/${user.uid}")
                        val selected = selectedRefs.any { it.path == ref.path }
                        Row(
                            Modifier.fillMaxWidth().clickable { toggleUser(ref) }
                                .padding(vertical = 6.dp, horizontal = 8.dp)
                                .background(
                                    if (selected) SchedulerSecondary.copy(alpha = 0.2f)
                                    else SchedulerSecondaryBackground,
                                    RoundedCornerShape(12.dp)
                                )
                                .padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Box {
                                UserAvatar(ChatUserData(displayName = user.displayName, photoUrl = user.photoUrl), 44.dp)
                                Box(
                                    Modifier.align(Alignment.BottomEnd).offset(x = 4.dp, y = 4.dp)
                                        .size(12.dp).clip(CircleShape)
                                        .background(if (user.isAvailable) SchedulerSuccess else SchedulerError)
                                )
                            }
                            Spacer(Modifier.width(12.dp))
                            Text(
                                user.displayName, Modifier.weight(1f),
                                color = if (selected) Color.White else SchedulerPrimaryText,
                                fontWeight = FontWeight.Medium
                            )
                            Box(
                                Modifier.size(22.dp).clip(RoundedCornerShape(4.dp))
                                    .background(if (selected) SchedulerPrimary else Color.Transparent)
                                    .then(if (!selected) Modifier.border(2.dp, SchedulerSecondaryText, RoundedCornerShape(4.dp)) else Modifier),
                                contentAlignment = Alignment.Center
                            ) {
                                if (selected) Icon(Icons.Default.Check, null, Modifier.size(14.dp), tint = Color.White)
                            }
                        }
                    }
                    item { Spacer(Modifier.height(100.dp)) }
                }
            }
        }

        Box(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                .background(Brush.verticalGradient(listOf(SchedulerSecondaryBackground.copy(alpha = 0.5f), SchedulerSecondaryBackground)))
                .padding(horizontal = 16.dp, vertical = 16.dp)
        ) {
            Button(
                onClick = submit,
                enabled = !isSubmitting,
                modifier = Modifier.fillMaxWidth().height(50.dp),
                shape = RoundedCornerShape(25.dp),
                colors = ButtonDefaults.buttonColors(containerColor = SchedulerPrimary)
            ) {
                Text(if (isSubmitting) "Sending..." else "Send Invites", color = Color.White, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}
