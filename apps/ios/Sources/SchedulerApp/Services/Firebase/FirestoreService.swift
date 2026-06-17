import Foundation
import Combine

protocol FirestoreServiceProtocol {
    func fetchDocument<T: Codable>(collection: String, documentId: String) async throws -> T
    func fetchDocuments<T: Codable>(collection: String, whereField field: String, isEqualTo value: Any) async throws -> [T]
    func addDocument<T: Codable>(collection: String, data: T) async throws -> String
    func updateDocument(collection: String, documentId: String, data: [String: Any]) async throws
    func deleteDocument(collection: String, documentId: String) async throws
    func listen<T: Codable>(collection: String, whereField field: String, isEqualTo value: Any) -> AnyPublisher<[T], Error>
}

enum FirestoreCollection: String {
    case schedules = "schedules"
    case shifts = "shifts"
    case employees = "employees"
    case users = "users"
    case tenants = "tenants"
}
