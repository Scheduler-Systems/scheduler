import FirebaseCore
import SwiftUI

@main
struct SchedulerApp: App {
    @StateObject private var router = Router()
    @StateObject private var auth = AuthViewModel()

    private let scheduleService: ScheduleDataServiceProtocol

    init() {
        // Firebase must be configured before any Auth/Firestore use. This was
        // missing from the native migration, which crashed/failed Firebase at
        // launch. Requires GoogleService-Info.plist in the app bundle.
        FirebaseApp.configure()

        let baseURL = Bundle.main.object(forInfoDictionaryKey: "SCHEDULER_API_URL") as? String
            ?? ProcessInfo.processInfo.environment["SCHEDULER_API_URL"]
            ?? "http://127.0.0.1:4180"

        guard let url = URL(string: baseURL) else {
            fatalError("Invalid SCHEDULER_API_URL: \(baseURL)")
        }

        self.scheduleService = ScheduleApiService(api: ApiClient(baseURL: url))
    }

    var body: some Scene {
        WindowGroup {
            NavigationStack(path: $router.path) {
                LoginView()
                    .navigationDestination(for: Route.self) { route in
                        destination(for: route)
                    }
            }
            .environmentObject(router)
            .environmentObject(auth)
        }
    }

    @ViewBuilder
    private func destination(for route: Route) -> some View {
        switch route {
        case .login:
            LoginView()
        case .onboarding:
            OnboardingView()
        case .createAccount:
            CreateAccountView()
        case .getName:
            GetNameView()
        case .chooseRole:
            ChooseRoleView()
        case .phoneSignIn:
            PhoneSignInView()
        case .passwordReset:
            PasswordResetView()
        case .verifyEmail:
            VerifyEmailView()
        case .home:
            HomeView(scheduleService: scheduleService, authViewModel: auth)
        case .scheduleList:
            ScheduleListView(vm: HomeViewModel(scheduleService: scheduleService, authViewModel: auth))
        case .scheduleDetail(let id):
            ScheduleDetailPlaceholder(id: id)
        case .scheduleBuilder:
            ScheduleBuilderView()
        case .employeeList:
            EmployeeListView()
        case .employeeDetail(let id):
            EmployeeDetailPlaceholder(id: id)
        case .settings:
            SettingsView()
        case .profile:
            ProfileView()
        }
    }
}

struct ScheduleDetailPlaceholder: View {
    let id: String
    var body: some View {
        Text("Schedule Detail: \(id)")
            .navigationTitle("Schedule")
    }
}

struct EmployeeListView: View {
    var body: some View {
        Text("Employee List")
            .navigationTitle("Employees")
    }
}

struct EmployeeDetailPlaceholder: View {
    let id: String
    var body: some View {
        Text("Employee Detail: \(id)")
            .navigationTitle("Employee")
    }
}
