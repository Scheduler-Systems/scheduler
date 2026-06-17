package com.schedulersystems.scheduler.ui.screens.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Send
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
import com.google.firebase.Timestamp
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.DocumentReference
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.ListenerRegistration
import com.schedulersystems.scheduler.ui.theme.*
import kotlinx.coroutines.tasks.await
import java.util.*

data class ChatMessage(
    val id: String = "",
    val user: DocumentReference? = null,
    val text: String = "",
    val timestamp: Date? = null,
    val image: String = ""
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatDetailsScreen(
    chatId: String,
    onNavigateBack: () -> Unit
) {
    val db = FirebaseFirestore.getInstance()
    val currentUserUid = FirebaseAuth.getInstance().currentUser?.uid ?: ""
    val currentUserRef = db.document("users/$currentUserUid")
    val chatRef = db.document("chats/$chatId")

    var messages by remember { mutableStateOf<List<ChatMessage>>(emptyList()) }
    var userDocs by remember { mutableStateOf<Map<String, ChatUserData>>(emptyMap()) }
    var messageText by remember { mutableStateOf("") }
    var isLoading by remember { mutableStateOf(true) }
    var chatName by remember { mutableStateOf("Chat") }
    val listState = rememberLazyListState()

    LaunchedEffect(chatId) {
        val chatDoc = try { chatRef.get().await() } catch (_: Exception) { null }
        chatDoc?.let { doc ->
            val schedRef = doc.get("schedule_ref") as? DocumentReference
            schedRef?.let { ref ->
                val schedDoc = try { ref.get().await() } catch (_: Exception) { null }
                val name = schedDoc?.getString("schedule_name") ?: "Chat"
                chatName = "$name - Group Chat"
            }
        }

        try {
            chatRef.update("last_message_seen_by", FieldValue.arrayUnion(currentUserRef)).await()
        } catch (_: Exception) {}

        chatRef.collection("chat_messages")
            .orderBy("timestamp")
            .addSnapshotListener { snap, _ ->
                val list = snap?.documents?.mapNotNull { doc ->
                    val data = doc.data ?: return@mapNotNull null
                    ChatMessage(
                        id = doc.id,
                        user = data["user"] as? DocumentReference,
                        text = data["text"] as? String ?: "",
                        timestamp = data["timestamp"] as? Date,
                        image = data["image"] as? String ?: ""
                    )
                } ?: emptyList()
                messages = list
                isLoading = false
            }
    }

    LaunchedEffect(messages.size) {
        if (messages.isNotEmpty()) {
            listState.animateScrollToItem(messages.size - 1)
        }
    }

    Surface(color = SchedulerPrimary) {
        TopAppBar(
            title = { Text(chatName, color = Color.White, maxLines = 1) },
            navigationIcon = {
                IconButton(onClick = onNavigateBack) {
                    Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = Color.White)
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = SchedulerPrimary)
        )
    }

    Column(Modifier.fillMaxSize().background(SchedulerPrimaryBackground)) {
        if (isLoading) {
            Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(color = SchedulerPrimary)
            }
        } else {
            LazyColumn(
                Modifier.weight(1f).padding(horizontal = 8.dp),
                state = listState
            ) {
                items(messages, key = { it.id }) { msg ->
                    val isCurrentUser = msg.user?.path == currentUserRef.path
                    MessageBubble(msg = msg, isCurrentUser = isCurrentUser, db = db)
                }
            }
        }

        HorizontalDivider(color = SchedulerLineColor)

        Row(
            Modifier.padding(horizontal = 12.dp, vertical = 8.dp).fillMaxWidth(),
            verticalAlignment = Alignment.Bottom
        ) {
            OutlinedTextField(
                value = messageText,
                onValueChange = { messageText = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("Type a message...") },
                shape = RoundedCornerShape(8.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor = SchedulerPrimary,
                    unfocusedBorderColor = SchedulerLineColor
                ),
                maxLines = 3
            )
            Spacer(Modifier.width(8.dp))
            IconButton(
                onClick = {
                    val trimmed = messageText.trim()
                    if (trimmed.isEmpty()) return@IconButton
                    messageText = ""

                    val msgData = mapOf(
                        "user" to currentUserRef,
                        "chat" to chatRef,
                        "text" to trimmed,
                        "timestamp" to FieldValue.serverTimestamp(),
                        "image" to "",
                        "video" to ""
                    )
                    chatRef.collection("chat_messages").add(msgData)

                    chatRef.update(mapOf(
                        "last_message" to trimmed,
                        "last_message_time" to FieldValue.serverTimestamp(),
                        "last_message_sent_by" to currentUserRef,
                        "last_message_seen_by" to listOf(currentUserRef)
                    ))
                },
                modifier = Modifier.size(40.dp).clip(CircleShape).background(SchedulerPrimary)
            ) {
                Icon(Icons.Default.Send, "Send", tint = Color.White, modifier = Modifier.size(20.dp))
            }
        }
    }
}

@Composable
fun MessageBubble(msg: ChatMessage, isCurrentUser: Boolean, db: FirebaseFirestore) {
    var userDoc by remember { mutableStateOf<ChatUserData?>(null) }

    LaunchedEffect(msg.user) {
        msg.user?.let { ref ->
            val doc = try { ref.get().await() } catch (_: Exception) { null }
            doc?.let {
                userDoc = ChatUserData(
                    displayName = it.getString("display_name") ?: "?",
                    photoUrl = it.getString("photo_url") ?: ""
                )
            }
        }
    }

    if (isCurrentUser) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            Column(horizontalAlignment = Alignment.End, modifier = Modifier.widthIn(max = 300.dp)) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text("Me", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = SchedulerPrimaryText)
                    Spacer(Modifier.width(4.dp))
                    msg.timestamp?.let {
                        Text(relativeTime(it), fontSize = 9.sp, color = SchedulerSecondaryText)
                    }
                }
                Box(
                    Modifier.padding(top = 2.dp).background(SchedulerPrimary, RoundedCornerShape(8.dp)).padding(12.dp)
                ) {
                    Text(msg.text.ifEmpty { "--" }, color = Color.White, fontSize = 14.sp)
                }
                if (msg.image.isNotEmpty()) {
                    AsyncImage(
                        model = msg.image, contentDescription = null,
                        modifier = Modifier.padding(top = 4.dp).size(width = 200.dp, height = 150.dp).clip(RoundedCornerShape(8.dp)),
                        contentScale = ContentScale.Crop
                    )
                }
            }
        }
    } else {
        Row(Modifier.fillMaxWidth()) {
            UserAvatar(userDoc ?: ChatUserData(displayName = "?"), 36.dp)
            Spacer(Modifier.width(8.dp))
            Column(modifier = Modifier.widthIn(max = 280.dp)) {
                Row(verticalAlignment = Alignment.Bottom) {
                    Text(
                        userDoc?.displayName ?: "Loading...",
                        fontSize = 11.sp, fontWeight = FontWeight.Medium, color = SchedulerPrimaryText
                    )
                    Spacer(Modifier.width(4.dp))
                    msg.timestamp?.let {
                        Text(relativeTime(it), fontSize = 9.sp, color = SchedulerSecondaryText)
                    }
                }
                Box(
                    Modifier.padding(top = 2.dp)
                        .background(SchedulerSecondaryBackground, RoundedCornerShape(8.dp))
                        .padding(12.dp)
                ) {
                    Text(msg.text.ifEmpty { "--" }, color = SchedulerPrimaryText, fontSize = 14.sp)
                }
                if (msg.image.isNotEmpty()) {
                    AsyncImage(
                        model = msg.image, contentDescription = null,
                        modifier = Modifier.padding(top = 4.dp).size(width = 200.dp, height = 150.dp).clip(RoundedCornerShape(8.dp)),
                        contentScale = ContentScale.Crop
                    )
                }
            }
        }
    }

    Spacer(Modifier.height(4.dp))
}
