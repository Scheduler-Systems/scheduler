import Foundation
import Combine

@MainActor
class ScheduleViewModel: BaseViewModel {
    @Published var schedules: [Schedule] = []
    @Published var selectedSchedule: Schedule?

    private let scheduleService: ScheduleDataServiceProtocol

    init(scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleService = scheduleService
    }

    func loadSchedules(tenantId: String) async {
        isLoading = true
        defer { isLoading = false }

        do {
            schedules = try await scheduleService.fetchSchedules(tenantId: tenantId)
        } catch {
            handle(error)
        }
    }

    func selectSchedule(_ schedule: Schedule) {
        selectedSchedule = schedule
    }
}
