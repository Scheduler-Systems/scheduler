import Foundation

@MainActor
final class ChooseRoleViewModel: ObservableObject {
    @Published var selectedRole: UserRole?

    var onRoleSelected: ((UserRole) -> Void)?

    func selectManager() {
        selectedRole = .manager
        onRoleSelected?(.manager)
    }

    func selectEmployee() {
        selectedRole = .employee
        onRoleSelected?(.employee)
    }
}
