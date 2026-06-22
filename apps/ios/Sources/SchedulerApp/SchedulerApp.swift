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
            GetNameView(scheduleService: scheduleService)
        case .chooseRole:
            ChooseRoleView(scheduleService: scheduleService)
        case .phoneSignIn:
            PhoneSignInView()
        case .passwordReset:
            PasswordResetView()
        case .verifyEmail:
            VerifyEmailView()
        case .home:
            HomeView(scheduleService: scheduleService, authViewModel: auth)
        case .scheduleList:
            ScheduleListView(scheduleService: scheduleService, authViewModel: auth)
        case .archivedSchedules:
            ArchivedSchedulesView(scheduleService: scheduleService)
        case .scheduleDetail(let id):
            ScheduleDetailView(scheduleId: id, scheduleService: scheduleService)
        case .scheduleSettings(let id):
            ScheduleSettingsView(scheduleId: id, scheduleService: scheduleService)
        case .scheduleRequests(let id):
            ScheduleRequestsView(scheduleId: id, scheduleService: scheduleService)
        case .prioritiesSubmission(let id):
            PrioritiesSubmissionView(scheduleId: id, scheduleService: scheduleService)
        case .currentPriorities(let id):
            CurrentPrioritiesView(scheduleId: id, scheduleService: scheduleService)
        case .scheduleBuilder:
            ScheduleBuilderView(scheduleService: scheduleService)
        case .employeeList(let id):
            EmployeeListView(scheduleId: id, scheduleService: scheduleService)
        case .employeeDetail(let id):
            EmployeeDetailPlaceholder(id: id)
        case .settings:
            SettingsView()
        case .profile:
            ProfileView()
        case .policies:
            PoliciesView()
        }
    }
}

// Self-loading: the .scheduleDetail route only carries the id, so fetch the schedule
// (tenant = current user id) and show the real dashboard. Wires the previously-orphaned
// ScheduleDashboardView (the route was a "Schedule Detail: <id>" stub).
struct ScheduleDetailView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var schedule: Schedule?
    @State private var loadError: String?

    var body: some View {
        Group {
            if let schedule {
                ScheduleDashboardView(schedule: schedule, scheduleService: scheduleService)
            } else if let loadError {
                Text(loadError).foregroundColor(.red)
            } else {
                ProgressView()
            }
        }
        .navigationTitle("Schedule")
        .task {
            guard let tenantId = auth.currentUserId else { return }
            do {
                schedule = try await scheduleService.fetchSchedule(tenantId: tenantId, scheduleId: scheduleId)
            } catch {
                loadError = error.localizedDescription
            }
        }
    }
}

// Self-loading: fetches the schedule's roster (tenant = current user id) from the
// Go API and lists each employee, with a "+" to add one (POST /employees). Wires the
// previously-stub EmployeeListView, reached from the schedule dashboard.
struct EmployeeListView: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    @EnvironmentObject private var auth: AuthViewModel
    @State private var employees: [Employee] = []
    @State private var isLoading = true
    @State private var loadError: String?
    @State private var showAddSheet = false

    init(scheduleId: String, scheduleService: ScheduleDataServiceProtocol) {
        self.scheduleId = scheduleId
        self.scheduleService = scheduleService
    }

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
            } else if let loadError {
                Text(loadError).foregroundColor(.red)
            } else if employees.isEmpty {
                Text("No employees yet").foregroundColor(.secondary)
            } else {
                List(employees) { employee in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(employee.displayName.isEmpty ? employee.email : employee.displayName)
                            .fontWeight(.semibold)
                        Text(employee.email).font(.subheadline).foregroundColor(.secondary)
                        if let phone = employee.phone, !phone.isEmpty {
                            Text(phone).font(.caption).foregroundColor(.secondary)
                        }
                        Text(employee.role.rawValue.capitalized)
                            .font(.caption)
                            .foregroundColor(.blue)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .navigationTitle("Employees")
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button { showAddSheet = true } label: { Image(systemName: "plus") }
                    .accessibilityLabel("Add Employee")
                    .accessibilityIdentifier("addEmployeeButton")
            }
        }
        .sheet(isPresented: $showAddSheet) {
            AddEmployeeSheet(scheduleId: scheduleId, scheduleService: scheduleService) {
                await load()
            }
            .environmentObject(auth)
        }
        .task { await load() }
    }

    private func load() async {
        guard let tenantId = auth.currentUserId else {
            isLoading = false
            return
        }
        do {
            employees = try await scheduleService.fetchEmployees(tenantId: tenantId, scheduleId: scheduleId)
            loadError = nil
        } catch {
            loadError = error.localizedDescription
        }
        isLoading = false
    }
}

// Add-employee form (name/email/phone) → POST /employees. On success, asks the parent
// to reload the roster and dismisses. The server is the source of truth for duplicate
// emails (409), surfaced here as an error.
struct AddEmployeeSheet: View {
    let scheduleId: String
    let scheduleService: ScheduleDataServiceProtocol
    let onAdded: () async -> Void
    @EnvironmentObject private var auth: AuthViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var email = ""
    @State private var phone = ""
    @State private var isAdding = false
    @State private var addError: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Employee") {
                    TextField("Name", text: $name)
                    TextField("Email", text: $email)
                        .autocorrectionDisabled(true)
                    TextField("Phone", text: $phone)
                }
                if let addError {
                    Text(addError).foregroundColor(.red).font(.caption)
                }
                Section {
                    Button(action: add) {
                        Text(isAdding ? "Adding…" : "Save Employee")
                            .frame(maxWidth: .infinity)
                    }
                    .disabled(email.isEmpty || isAdding)
                }
            }
            .navigationTitle("Add Employee")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func add() {
        guard let tenantId = auth.currentUserId else { addError = "Not signed in"; return }
        isAdding = true
        addError = nil
        Task {
            do {
                _ = try await scheduleService.addEmployee(
                    tenantId: tenantId, scheduleId: scheduleId,
                    name: name, email: email, phone: phone
                )
                await onAdded()
                isAdding = false
                dismiss()
            } catch {
                isAdding = false
                addError = error.localizedDescription
            }
        }
    }
}

struct EmployeeDetailPlaceholder: View {
    let id: String
    var body: some View {
        Text("Employee Detail: \(id)")
            .navigationTitle("Employee")
    }
}
