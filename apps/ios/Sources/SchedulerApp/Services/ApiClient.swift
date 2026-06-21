import Foundation
import FirebaseAuth

enum ApiError: LocalizedError {
    case invalidURL
    case notAuthenticated
    case network(URLError)
    case server(status: Int, message: String)
    case decode(String)
    case encode(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid API URL"
        case .notAuthenticated: return "Not authenticated"
        case .network(let err): return err.localizedDescription
        case .server(let status, let message): return "[\(status)] \(message)"
        case .decode(let msg): return "Decode error: \(msg)"
        case .encode(let msg): return "Encode error: \(msg)"
        }
    }
}

protocol ApiClientProtocol {
    func fetchSchedules(tenantId: String) async throws -> [ScheduleResponse]
    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> ScheduleResponse
    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [EmployeeResponse]
    func addEmployee(tenantId: String, scheduleId: String, body: AddEmployeeRequest) async throws -> EmployeeResponse
    func createSchedule(tenantId: String, body: CreateScheduleRequest) async throws -> ScheduleResponse
    func updateSchedule(tenantId: String, scheduleId: String, body: UpdateScheduleRequest) async throws -> ScheduleResponse
    func deleteSchedule(tenantId: String, scheduleId: String) async throws -> DeleteResponse
    func putAvailability(tenantId: String, scheduleId: String, body: AvailabilityRequest) async throws -> AvailabilityResponse
    func createDraft(tenantId: String, scheduleId: String, body: DraftRequest) async throws -> DraftResponse
    func publishSchedule(tenantId: String, scheduleId: String, body: PublishRequest) async throws -> PublishResponse
    func createRequest(tenantId: String, scheduleId: String, body: ScheduleRequest) async throws -> ScheduleRequestResponse
}

final class ApiClient: ApiClientProtocol {
    private let base: URL
    private let session: URLSession
    private let encoder = JSONEncoder()
    private let decoder: JSONDecoder

    init(baseURL: URL, session: URLSession = .shared) {
        self.base = baseURL
        self.session = session
        self.decoder = JSONDecoder()

        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = formatter.date(from: string) { return date }
            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: string) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Invalid date: \(string)")
        }
    }

    private func makeRequest(path: String, method: String, tenantId: String, body: (any Encodable)? = nil) async throws -> URLRequest {
        let url = base.appendingPathComponent(path)
        var req = URLRequest(url: url)
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "content-type")

        guard let currentUser = Auth.auth().currentUser else {
            throw ApiError.notAuthenticated
        }

        let token = try await currentUser.getIDToken()
        req.setValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        req.setValue(tenantId, forHTTPHeaderField: "x-tenant-id")
        req.setValue(currentUser.uid, forHTTPHeaderField: "x-user-id")
        req.setValue("employee", forHTTPHeaderField: "x-user-role")
        req.setValue(UUID().uuidString, forHTTPHeaderField: "x-correlation-id")

        if let body {
            do {
                req.httpBody = try encoder.encode(AnyEncodable(body))
            } catch {
                throw ApiError.encode(error.localizedDescription)
            }
        }

        return req
    }

    func fetchSchedules(tenantId: String) async throws -> [ScheduleResponse] {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules", method: "GET", tenantId: tenantId)
        let wrapper: ListResponse<ScheduleResponse> = try await execute(req)
        return wrapper.items
    }

    func fetchSchedule(tenantId: String, scheduleId: String) async throws -> ScheduleResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)", method: "GET", tenantId: tenantId)
        return try await execute(req)
    }

    func fetchEmployees(tenantId: String, scheduleId: String) async throws -> [EmployeeResponse] {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/employees", method: "GET", tenantId: tenantId)
        let wrapper: ListResponse<EmployeeResponse> = try await execute(req)
        return wrapper.items
    }

    func addEmployee(tenantId: String, scheduleId: String, body: AddEmployeeRequest) async throws -> EmployeeResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/employees", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func createSchedule(tenantId: String, body: CreateScheduleRequest) async throws -> ScheduleResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func updateSchedule(tenantId: String, scheduleId: String, body: UpdateScheduleRequest) async throws -> ScheduleResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)", method: "PATCH", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func deleteSchedule(tenantId: String, scheduleId: String) async throws -> DeleteResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)", method: "DELETE", tenantId: tenantId)
        return try await execute(req)
    }

    func putAvailability(tenantId: String, scheduleId: String, body: AvailabilityRequest) async throws -> AvailabilityResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/availability", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func createDraft(tenantId: String, scheduleId: String, body: DraftRequest) async throws -> DraftResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/drafts", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func publishSchedule(tenantId: String, scheduleId: String, body: PublishRequest) async throws -> PublishResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/publish", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    func createRequest(tenantId: String, scheduleId: String, body: ScheduleRequest) async throws -> ScheduleRequestResponse {
        let req = try await makeRequest(path: "v1/tenants/\(tenantId)/schedules/\(scheduleId)/requests", method: "POST", tenantId: tenantId, body: body)
        return try await execute(req)
    }

    private func execute<T: Decodable>(_ request: URLRequest) async throws -> T {
        let data: Data
        let response: URLResponse

        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError {
            throw ApiError.network(error)
        }

        guard let http = response as? HTTPURLResponse else {
            throw ApiError.server(status: 0, message: "Invalid response")
        }

        guard (200...299).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw ApiError.server(status: http.statusCode, message: body)
        }

        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw ApiError.decode(error.localizedDescription)
        }
    }
}

private struct AnyEncodable: Encodable {
    let value: any Encodable

    init(_ value: any Encodable) {
        self.value = value
    }

    func encode(to encoder: Encoder) throws {
        try value.encode(to: encoder)
    }
}

struct ListResponse<T: Decodable>: Decodable {
    let items: [T]
}
