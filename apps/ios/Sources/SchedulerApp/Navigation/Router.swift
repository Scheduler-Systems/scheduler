import Foundation
import SwiftUI

enum Route: Hashable {
    case login
    case onboarding
    case createAccount
    case getName
    case chooseRole
    case phoneSignIn
    case passwordReset
    case verifyEmail
    case home
    case scheduleList
    case archivedSchedules
    case scheduleDetail(Schedule.ID)
    case scheduleSettings(Schedule.ID)
    case scheduleRequests(Schedule.ID)
    case scheduleBuilder
    case employeeList(Schedule.ID)
    case employeeDetail(Employee.ID)
    case settings
    case profile
}

@MainActor
class Router: ObservableObject {
    @Published var path = NavigationPath()

    func push(_ route: Route) {
        path.append(route)
    }

    func pop() {
        if !path.isEmpty {
            path.removeLast()
        }
    }

    func popToRoot() {
        path = NavigationPath()
    }

    func replace(with route: Route) {
        path = NavigationPath()
        path.append(route)
    }
}
