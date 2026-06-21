import FirebaseAuth
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

        // Zero-account e2e: point Auth at the local Firebase Auth emulator when launched for
        // testing. Triggered by env USE_FIREBASE_EMULATOR=true, UserDefaults `-useFirebaseEmulator`,
        // or ANY process launch argument mentioning useFirebaseEmulator (Maestro passes its
        // launchArguments map in a form that doesn't always reach NSUserDefaults, so match the
        // raw argv too). iOS Simulator reaches the host machine via 127.0.0.1 (Android uses 10.0.2.2).
        let env = ProcessInfo.processInfo.environment
        let emulatorOn = env["USE_FIREBASE_EMULATOR"] == "true"
            || UserDefaults.standard.bool(forKey: "useFirebaseEmulator")
            || ProcessInfo.processInfo.arguments.contains { $0.localizedCaseInsensitiveContains("useFirebaseEmulator") }
        if emulatorOn {
            let host = env["FIREBASE_EMULATOR_HOST"] ?? "127.0.0.1"
            Auth.auth().useEmulator(withHost: host, port: 9099)
            // Zero-account e2e must start logged out. Maestro's clearState wipes the app
            // container but NOT the iOS keychain, so a prior sign-in (e.g. create-account)
            // persists and the app would launch straight to home. Clear it for a deterministic start.
            try? Auth.auth().signOut()
        }

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
