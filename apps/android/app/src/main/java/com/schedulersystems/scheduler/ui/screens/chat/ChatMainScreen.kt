package com.schedulersystems.scheduler.ui.screens.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.ListenerRegistration
import com.google.firebase.firestore.toObject
import com.schedulersystems.scheduler.ui.theme.*
import kotlinx.coroutines.tasks.await
import java.text.SimpleDateFormat
import java.util.*

data class ChatRecord(
    val id: String = "",
    val users: List<DocumentReference> = emptyList(),
    val lastMessage: String = "",
    val lastMessageTime: Date? = null,
    val lastMessageSeenBy: List<DocumentReference> = emptyList(),
    val scheduleRef: DocumentReference? = null
)

data class ChatUserData(
    val uid: String = "",
    val displayName: String = "",
    val photoUrl: String = "",
    val isAvailable: Boolean = true,
    val phoneNumber: String = "",
    val email: String = ""
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatMainScreen(
    onNavigateBack: () -> Unit,
    onNavigateToChatDetails: (String) -> Unit
) {
    val db = FirebaseFirestore.getInstance()
    val currentUserUid = FirebaseAuth.getInstance().currentUser?.uid ?: ""
    val currentUserRef = if (currentUserUid.isNotBlank()) db.document("users/$currentUserUid") else null

    var chats by remember { mutableStateOf<List<ChatRecord>>(emptyList()) }
    var isLoading by remember { mutableStateOf(true) }
    var errorMsg by remember { mutableStateOf<String?>(null) }
    var scheduleNames by remember { mutableStateOf<Map<String, String>>(emptyMap()) }
    var otherUsers by remember { mutableStateOf<Map<String, ChatUserData>>(emptyMap()) }

    LaunchedEffect(currentUserRef) {
        if (currentUserRef == null) {
            isLoading = false
            return@LaunchedEffect
        }
        try {
            db.collection("chats")
                .whereArrayContains("users", currentUserRef)
                .orderBy("last_message_time")
                .addSnapshotListener { snap, error ->
                    if (error != null) {
                        isLoading = false
                        errorMsg = error.message
                        return@addSnapshotListener
                    }
                    val list = snap?.documents?.mapNotNull { doc ->
                        try {
                            val data = doc.data ?: return@mapNotNull null
                            ChatRecord(
                                id = doc.id,
                                users = (data["users"] as? List<DocumentReference>) ?: emptyList(),
                                lastMessage = data["last_message"] as? String ?: "",
                                lastMessageTime = data["last_message_time"] as? Date,
                                lastMessageSeenBy = (data["last_message_seen_by"] as? List<DocumentReference>) ?: emptyList(),
                                scheduleRef = data["schedule_ref"] as? DocumentReference
                            )
                        } catch (e: Exception) { null }
                    } ?: emptyList()
                    chats = list
                    isLoading = false
                }
        } catch (e: Exception) {
            isLoading = false
            errorMsg = e.message
        }
    }

    Surface(color = SchedulerPrimary) {
        Column {
            TopAppBar(
                title = { Text("My Chats", color = Color.White) },
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = SchedulerPrimary)
            )
        }
    }

    Box(Modifier.fillMaxSize().background(SchedulerPrimaryBackground)) {
        when {
            isLoading -> {
                CircularProgressIndicator(
                    Modifier.align(Alignment.Center),
                    color = SchedulerPrimary
                )
            }
            errorMsg != null -> {
                Column(Modifier.align(Alignment.Center).padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(errorMsg ?: "Error", color = SchedulerError)
                    Spacer(Modifier.height(12.dp))
                    Button(onClick = { isLoading = true; errorMsg = null }) {
                        Text("Retry")
                    }
                }
            }
            chats.isEmpty() -> {
                Column(
                    Modifier.align(Alignment.Center).padding(24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Icon(Icons.Default.ChatBubbleOutline, null, Modifier.size(80.dp), tint = SchedulerSecondaryText)
                    Spacer(Modifier.height(24.dp))
                    Text("No chats available", style = MaterialTheme.typography.titleLarge, color = SchedulerPrimaryText)
                    Text("You don't have any active chats yet. Start a conversation to see it here!",
                        style = MaterialTheme.typography.bodyMedium, color = SchedulerSecondaryText,
                        modifier = Modifier.padding(horizontal = 16.dp))
                    Spacer(Modifier.height(24.dp))
                    Button(onClick = onNavigateBack, colors = ButtonDefaults.buttonColors(containerColor = SchedulerPrimary)) {
                        Text("Go to Home")
                    }
                }
            }
            else -> {
                Column {
                    Text("Below are your chats and group conversations.",
                        style = MaterialTheme.typography.labelMedium,
                        color = SchedulerSecondaryText,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
                    LazyColumn {
                        currentUserRef?.let { userRef ->
                            items(chats) { chat ->
                                ChatListItem(
                                    chat = chat,
                                    currentUserRef = userRef,
                                    db = db,
                                    onClick = { onNavigateToChatDetails(chat.id) }
                                )
                                HorizontalDivider(color = SchedulerPrimary.copy(alpha = 0.15f))
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun ChatListItem(
    chat: ChatRecord,
    currentUserRef: DocumentReference,
    db: FirebaseFirestore,
    onClick: () -> Unit
) {
    var otherUser by remember { mutableStateOf<ChatUserData?>(null) }
    var lastUser by remember { mutableStateOf<ChatUserData?>(null) }
    var scheduleName by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(chat.id) {
        val otherRefs = chat.users.filter { it.path != currentUserRef.path }
        otherRefs.firstOrNull()?.let { ref ->
            val doc = try { ref.get().await() } catch (_: Exception) { null }
            doc?.let {
                otherUser = ChatUserData(
                    uid = it.id,
                    displayName = it.getString("display_name") ?: "",
                    photoUrl = it.getString("photo_url") ?: "",
                    isAvailable = it.getBoolean("is_available") ?: true
                )
            }
        }
        chat.users.lastOrNull()?.let { ref ->
            val doc = try { ref.get().await() } catch (_: Exception) { null }
            doc?.let {
                lastUser = ChatUserData(
                    uid = it.id,
                    displayName = it.getString("display_name") ?: "",
                    photoUrl = it.getString("photo_url") ?: ""
                )
            }
        }
        chat.scheduleRef?.let { ref ->
            val doc = try { ref.get().await() } catch (_: Exception) { null }
            scheduleName = doc?.getString("schedule_name")
        }
    }

    val isUnseen = !chat.lastMessageSeenBy.any { it.path == currentUserRef.path }

    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 10.dp)
    ) {
        Box(Modifier.size(44.dp, 54.dp)) {
            if (otherUser != null) {
                UserAvatar(otherUser!!, 32.dp)
            }
            if (lastUser != null) {
                Box(Modifier.offset(x = 12.dp, y = 12.dp)) {
                    UserAvatar(lastUser!!, 32.dp)
                }
            }
        }

        Column(Modifier.weight(1f).padding(start = 8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    scheduleName?.let { "$it - Group Chat" } ?: (otherUser?.displayName ?: "Chat"),
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                    color = SchedulerPrimaryText,
                    maxLines = 1,
                    modifier = Modifier.weight(1f)
                )
                if (isUnseen) {
                    Box(
                        Modifier.size(12.dp).clip(CircleShape).background(SchedulerSecondary)
                            .padding(start = 8.dp)
                    )
                }
            }
            Text(
                chat.lastMessage.ifEmpty { "--" },
                style = MaterialTheme.typography.labelMedium,
                color = SchedulerSecondaryText,
                maxLines = 1
            )
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(
                    chat.lastMessageTime?.let { relativeTime(it) } ?: "--",
                    style = MaterialTheme.typography.labelSmall,
                    color = SchedulerSecondaryText
                )
                Icon(Icons.Default.ChevronRight, null, Modifier.size(20.dp), tint = SchedulerSecondaryText)
            }
        }
    }
}

@Composable
fun UserAvatar(user: ChatUserData, size: androidx.compose.ui.unit.Dp) {
    if (user.photoUrl.isNotEmpty()) {
        AsyncImage(
            model = user.photoUrl,
            contentDescription = null,
            modifier = Modifier.size(size).clip(RoundedCornerShape(size.value * 0.25f)),
            contentScale = ContentScale.Crop
        )
    } else {
        Box(
            Modifier.size(size).clip(RoundedCornerShape(size.value * 0.25f)).background(SchedulerSecondary),
            contentAlignment = Alignment.Center
        ) {
            Text(
                user.displayName.firstOrNull()?.uppercase() ?: "?",
                color = Color.White,
                fontSize = (size.value * 0.45f).sp,
                fontWeight = FontWeight.Bold
            )
        }
    }
}

fun relativeTime(date: Date): String {
    val diff = System.currentTimeMillis() - date.time
    val minutes = diff / 60000
    val hours = minutes / 60
    val days = hours / 24
    return when {
        minutes < 1 -> "Just now"
        minutes < 60 -> "${minutes}m ago"
        hours < 24 -> "${hours}h ago"
        days < 7 -> "${days}d ago"
        else -> SimpleDateFormat("dd/MM/yy", Locale.getDefault()).format(date)
    }
}
