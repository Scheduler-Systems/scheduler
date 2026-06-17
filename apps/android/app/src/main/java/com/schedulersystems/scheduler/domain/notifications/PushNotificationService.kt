package com.schedulersystems.scheduler.domain.notifications

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.messaging.FirebaseMessaging
import com.schedulersystems.scheduler.MainActivity
import com.schedulersystems.scheduler.R
import kotlinx.coroutines.tasks.await

object PushNotificationService {

    private const val CHANNEL_DEFAULT = "scheduler_default"
    private const val CHANNEL_HIGH = "scheduler_high"

    fun createNotificationChannels(context: Context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val defaultChannel = NotificationChannel(
                CHANNEL_DEFAULT,
                "General Notifications",
                NotificationManager.IMPORTANCE_DEFAULT
            ).apply { description = "General schedule notifications" }

            val highChannel = NotificationChannel(
                CHANNEL_HIGH,
                "Important Notifications",
                NotificationManager.IMPORTANCE_HIGH
            ).apply { description = "Urgent schedule updates and messages" }

            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(defaultChannel)
            manager.createNotificationChannel(highChannel)
        }
    }

    suspend fun saveTokenToFirestore(userId: String, token: String) {
        val db = FirebaseFirestore.getInstance()
        db.collection("ff_user_push_notifications").document(userId).set(
            mapOf(
                "fcmToken" to token,
                "deviceType" to "Android",
                "updatedAt" to FieldValue.serverTimestamp()
            )
        ).await()
    }

    fun subscribeToTopics() {
        val messaging = FirebaseMessaging.getInstance()
        val topics = listOf("schedule_updates", "new_requests", "chat_messages")
        topics.forEach { topic ->
            messaging.subscribeToTopic(topic).addOnCompleteListener { task ->
                if (!task.isSuccessful) {
                    // Topic subscription logging
                }
            }
        }
    }

    fun showNotification(
        context: Context,
        title: String,
        body: String,
        initialPageName: String? = null,
        parameterData: String? = null,
        highPriority: Boolean = false
    ) {
        val intent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra("initialPageName", initialPageName)
            putExtra("parameterData", parameterData)
        }

        val pendingIntent = PendingIntent.getActivity(
            context, System.currentTimeMillis().toInt(),
            intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val channelId = if (highPriority) CHANNEL_HIGH else CHANNEL_DEFAULT

        val notification = NotificationCompat.Builder(context, channelId)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(body)
            .setAutoCancel(true)
            .setPriority(if (highPriority) NotificationCompat.PRIORITY_HIGH else NotificationCompat.PRIORITY_DEFAULT)
            .setContentIntent(pendingIntent)
            .build()

        val notificationManager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(System.currentTimeMillis().toInt(), notification)
    }

    suspend fun triggerPushNotification(
        title: String,
        text: String,
        userRefs: List<String>,
        initialPageName: String,
        parameterData: Map<String, Any>
    ) {
        if (title.isBlank() || text.isBlank()) return

        val db = FirebaseFirestore.getInstance()
        db.collection("ff_user_push_notifications").add(
            mapOf(
                "notification_title" to title,
                "notification_text" to text,
                "user_refs" to userRefs.joinToString(","),
                "initial_page_name" to initialPageName,
                "parameter_data" to parameterData.toString(),
                "timestamp" to FieldValue.serverTimestamp()
            )
        ).await()
    }
}
