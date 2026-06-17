import Foundation
import Combine

@MainActor
final class HomeViewModel: BaseViewModel {
    @Published var displayName: String?
    @Published var schedules: [Schedule] = []
    @Published var schedulesInvolvedCount = 0
    @Published var hasInitComplete = false

    private let scheduleService: ScheduleDataServiceProtocol
    private var authViewModel: AuthViewModel?

    init(scheduleService: ScheduleDataServiceProtocol, authViewModel: AuthViewModel? = nil) {
        self.scheduleService = scheduleService
        self.authViewModel = authViewModel
    }

    func initialize() async {
        displayName = authViewModel?.currentUserDisplayName
        await loadSchedules()
        hasInitComplete = true
    }

    func loadSchedules() async {
        isLoading = true
        defer { isLoading = false }

        guard let tenantId = authViewModel?.currentUserId else { return }

        do {
            schedules = try await scheduleService.fetchSchedules(tenantId: tenantId)
            schedulesInvolvedCount = schedules.count
        } catch {
            handle(error)
        }
    }
}
