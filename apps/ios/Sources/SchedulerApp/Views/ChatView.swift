import SwiftUI
import FirebaseFirestore

/// Chat (parity with Android's Firestore-backed chat). Reads the same Firestore schema directly:
/// threads in top-level `chats` where `users` (array of DocumentReference → users/{uid})
/// array-contains the current user, ordered by `last_message_time`; messages in the
/// `chats/{id}/chat_messages` subcollection. Firestore is pointed at the isolated chat emulator
/// (:8089, app project scheduler-ci-placeholder) in SchedulerApp when launched for the eval.

struct ChatThreadRow: Identifiable, Equatable {
    let id: String
    let lastMessage: String
}

@MainActor
final class ChatListModel: ObservableObject {
    @Published var threads: [ChatThreadRow] = []
    @Published var isLoading = true
    @Published var error: String?
    private var listener: ListenerRegistration?

    func start(uid: String) {
        let db = Firestore.firestore()
        let myRef = db.collection("users").document(uid)
        listener = db.collection("chats")
            .whereField("users", arrayContains: myRef)
            .order(by: "last_message_time")
            .addSnapshotListener { [weak self] snap, err in
                guard let self else { return }
                self.isLoading = false
                if let err { self.error = err.localizedDescription; return }
                self.threads = (snap?.documents ?? []).map {
                    ChatThreadRow(id: $0.documentID, lastMessage: $0.data()["last_message"] as? String ?? "")
                }
            }
    }

    func stop() { listener?.remove(); listener = nil }
}

struct ChatListView: View {
    @EnvironmentObject private var auth: AuthViewModel
    @EnvironmentObject private var router: Router
    @StateObject private var model = ChatListModel()

    var body: some View {
        Group {
            if model.isLoading {
                ProgressView()
            } else if let error = model.error {
                Text("Error: \(error)").foregroundColor(.red).padding()
            } else if model.threads.isEmpty {
                Text("No chats available").foregroundColor(.secondary)
            } else {
                List(model.threads) { thread in
                    Button(action: { router.push(.chatThread(thread.id)) }) {
                        Text(thread.lastMessage.isEmpty ? "(no messages)" : thread.lastMessage)
                    }
                }
            }
        }
        .navigationTitle("Chat")
        .task {
            guard let uid = auth.currentUserId else { return }
            model.start(uid: uid)
        }
        .onDisappear { model.stop() }
    }
}

@MainActor
final class ChatThreadModel: ObservableObject {
    @Published var messages: [ChatThreadRow] = []  // reuse: id=docID, lastMessage=text
    private var listener: ListenerRegistration?

    func start(chatId: String) {
        listener = Firestore.firestore()
            .collection("chats").document(chatId).collection("chat_messages")
            .order(by: "timestamp")
            .addSnapshotListener { [weak self] snap, _ in
                self?.messages = (snap?.documents ?? []).map {
                    ChatThreadRow(id: $0.documentID, lastMessage: $0.data()["text"] as? String ?? "")
                }
            }
    }

    func stop() { listener?.remove(); listener = nil }
}

struct ChatThreadView: View {
    let chatId: String
    @StateObject private var model = ChatThreadModel()

    var body: some View {
        List(model.messages) { msg in
            Text(msg.lastMessage)
        }
        .navigationTitle("Messages")
        .task { model.start(chatId: chatId) }
        .onDisappear { model.stop() }
    }
}
