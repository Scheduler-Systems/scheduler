package com.schedulersystems.scheduler.domain.notifications

import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.FirebaseFirestore
import com.google.firebase.firestore.FieldValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class SchedulerMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        super.onNewToken(token)

        val userId = FirebaseAuth.getInstance().currentUser?.uid ?: return

        CoroutineScope(Dispatchers.IO).launch {
            PushNotificationService.saveTokenToFirestore(userId, token)
            PushNotificationService.subscribeToTopics()
        }
    }

    override fun onMessageReceived(remoteMessage: RemoteMessage) {
        super.onMessageReceived(remoteMessage)

        val title = remoteMessage.notification?.title
            ?: remoteMessage.data["notification_title"]
            ?: "New Notification"

        val body = remoteMessage.notification?.body
            ?: remoteMessage.data["notification_text"]
            ?: ""

        val initialPageName = remoteMessage.data["initial_page_name"]
        val parameterData = remoteMessage.data["parameter_data"]

        PushNotificationService.showNotification(
            context = this,
            title = title,
            body = body,
            initialPageName = initialPageName,
            parameterData = parameterData
        )
    }

    override fun onMessageSent(msgId: String) {
        super.onMessageSent(msgId)
    }

    override fun onSendError(msgId: String, exception: Exception) {
        super.onSendError(msgId, exception)
    }
}
