# Flutter to Native Swift Migration Architecture

## Overview

This document outlines the architecture for migrating the Scheduler Flutter iOS application to native Swift/SwiftUI.

**Issue**: #1843  
**Status**: Planning Phase  
**Target**: iOS 15.0+

---

## Flutter App Analysis

### Screens/Views Inventory

| Category | Count | Examples |
|----------|-------|----------|
| Features | 13 | home, onboarding, my_schedules, new_schedule2, schedule_dashboard |
| Production Pages | 15 | add_employee, archived_schedules, current_priorities, employee_list |
| Production Components | 18 | drawer, notifications, update_dialog, critical_update |
| Walkthroughs | 8 | first_time_employer, first_time_employee, first_time_chat |
| **Total Widgets** | **70** | |

### State Management Pattern

**Current**: Provider pattern with ChangeNotifier

Key providers:
- `SecureFirebaseProvider` - Firebase service management
- `PremiumStatusProvider` - Subscription/premium status
- `FirebaseUserProvider` - Authentication state

**Target**: Combine + ObservableObject (MVVM)

### Firebase Integrations

| Service | Flutter Package | Native SDK |
|---------|-----------------|------------|
| Core | firebase_core | Firebase iOS SDK 11.x |
| Auth | firebase_auth | FirebaseAuth |
| Firestore | cloud_firestore | FirebaseFirestore |
| Functions | cloud_functions | FirebaseFunctions |
| Analytics | firebase_analytics | FirebaseAnalytics |
| Crashlytics | firebase_crashlytics | FirebaseCrashlytics |
| Messaging | firebase_messaging | FirebaseMessaging |
| Performance | firebase_performance | FirebasePerformance |
| Remote Config | firebase_remote_config | FirebaseRemoteConfig |
| Storage | firebase_storage | FirebaseStorage |
| App Check | firebase_app_check | FirebaseAppCheck |

### Platform Channels

| Channel | Purpose | Native Implementation |
|---------|---------|----------------------|
| `secure_intercom` | Intercom SDK (Android) | N/A |
| `secure_intercom_ios` | Intercom SDK (iOS) | Intercom iOS SDK |

### Third-Party Dependencies (iOS-relevant)

| Dependency | Purpose | Native Alternative |
|------------|---------|-------------------|
| google_sign_in_ios | Google Auth | GoogleSignIn iOS SDK |
| sign_in_with_apple | Apple Auth | AuthenticationServices |
| flutter_facebook_auth | Facebook Auth | FBSDKLoginKit |
| purchases_flutter | RevenueCat | RevenueCat iOS SDK |
| intercom_flutter | Support chat | Intercom iOS SDK |
| package_info_plus | App version | Bundle.main |
| shared_preferences | Local storage | UserDefaults |
| sqflite | Local database | SQLite / Core Data |
| image_picker_ios | Image selection | PHPickerViewController |
| url_launcher_ios | Deep links | UIApplication |
| webview_flutter_wkwebview | Web views | WKWebView |

---

## Native Swift Architecture

### App Structure

```
Sources/
├── SchedulerApp/
│   ├── SchedulerApp.swift              # @main entry point
│   ├── AppConfiguration.swift          # Firebase, dependencies setup
│   ├── AppDelegate.swift               # UIKit lifecycle hooks
│   │
│   ├── Views/
│   │   ├── ContentView.swift           # Root view with tab/role routing
│   │   ├── Home/
│   │   │   ├── HomeView.swift
│   │   │   └── HomeViewModel.swift
│   │   ├── Auth/
│   │   │   ├── LoginView.swift
│   │   │   ├── LoginViewModel.swift
│   │   │   ├── OnboardingView.swift
│   │   │   └── RoleSelectionView.swift
│   │   ├── Schedule/
│   │   │   ├── ScheduleListView.swift
│   │   │   ├── ScheduleDetailView.swift
│   │   │   ├── ScheduleBuilderView.swift
│   │   │   └── ScheduleViewModel.swift
│   │   ├── Employees/
│   │   │   ├── EmployeeListView.swift
│   │   │   ├── EmployeeDetailView.swift
│   │   │   └── EmployeeViewModel.swift
│   │   ├── Settings/
│   │   │   ├── SettingsView.swift
│   │   │   └── ProfileSettingsView.swift
│   │   └── Components/
│   │       ├── LoadingView.swift
│   │       ├── ErrorView.swift
│   │       └── EmptyStateView.swift
│   │
│   ├── ViewModels/
│   │   ├── BaseViewModel.swift
│   │   ├── AuthViewModel.swift
│   │   ├── ScheduleViewModel.swift
│   │   ├── EmployeeViewModel.swift
│   │   └── PremiumViewModel.swift
│   │
│   ├── Models/
│   │   ├── Schedule.swift
│   │   ├── Shift.swift
│   │   ├── Employee.swift
│   │   ├── User.swift
│   │   ├── Tenant.swift
│   │   └── DTOs/
│   │       ├── ScheduleDTO.swift
│   │       └── EmployeeDTO.swift
│   │
│   ├── Services/
│   │   ├── Firebase/
│   │   │   ├── FirebaseService.swift
│   │   │   ├── AuthService.swift
│   │   │   ├── FirestoreService.swift
│   │   │   ├── CloudFunctionsService.swift
│   │   │   └── RemoteConfigService.swift
│   │   ├── API/
│   │   │   ├── APIClient.swift
│   │   │   └── APIError.swift
│   │   ├── Storage/
│   │   │   ├── UserDefaultsService.swift
│   │   │   └── KeychainService.swift
│   │   ├── Auth/
│   │   │   ├── GoogleAuthService.swift
│   │   │   ├── AppleAuthService.swift
│   │   │   └── FacebookAuthService.swift
│   │   ├── RevenueCatService.swift
│   │   └── IntercomService.swift
│   │
│   ├── Navigation/
│   │   ├── Router.swift
│   │   ├── NavigationPath+Routes.swift
│   │   └── DeepLinkHandler.swift
│   │
│   ├── Extensions/
│   │   ├── Color+Theme.swift
│   │   ├── View+Extensions.swift
│   │   └── Date+Extensions.swift
│   │
│   └── Resources/
│       ├── Assets.xcassets
│       └── Localizable.strings
│
├── SchedulerAppTests/
│   └── ...
│
└── SchedulerAppUITests/
    └── ...
```

### MVVM Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│                         VIEW LAYER                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  SwiftUI    │    │  View       │    │  View       │         │
│  │  Views      │───▶│  Modifiers  │───▶│  Components │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ @ObservedObject / @StateObject
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      VIEW MODEL LAYER                           │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Observable  │    │ @Published  │    │ Combine     │         │
│  │ Object      │───▶│ Properties  │───▶│ Publishers  │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Service Injection
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       SERVICE LAYER                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Firebase    │    │ API         │    │ Storage     │         │
│  │ Services    │    │ Client      │    │ Services    │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Network/Database
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        DATA LAYER                               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │ Firebase    │    │ Firestore   │    │ Local       │         │
│  │ Auth        │    │ /Cloud Funcs│    │ Storage     │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

### Navigation Architecture

Using SwiftUI's native `NavigationStack` with `NavigationPath`:

```swift
enum Route: Hashable {
    case home
    case scheduleDetail(Schedule.ID)
    case scheduleBuilder
    case employeeList
    case employeeDetail(Employee.ID)
    case settings
    case login
    case onboarding
}

@MainActor
class Router: ObservableObject {
    @Published var path = NavigationPath()
    
    func push(_ route: Route) { path.append(route) }
    func pop() { if !path.isEmpty { path.removeLast() } }
    func popToRoot() { path = NavigationPath() }
}
```

### State Management

Using Combine with `@Published` properties:

```swift
@MainActor
class ScheduleViewModel: ObservableObject {
    @Published var schedules: [Schedule] = []
    @Published var isLoading = false
    @Published var error: Error?
    
    private let scheduleService: ScheduleServiceProtocol
    private var cancellables = Set<AnyCancellable>()
    
    init(scheduleService: ScheduleServiceProtocol) {
        self.scheduleService = scheduleService
    }
    
    func loadSchedules() async {
        isLoading = true
        defer { isLoading = false }
        
        do {
            schedules = try await scheduleService.fetchSchedules()
        } catch {
            self.error = error
        }
    }
}
```

---

## Migration Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Set up Xcode project with Swift Package Manager
- [ ] Configure Firebase iOS SDK
- [ ] Implement core models (Schedule, Shift, Employee, User)
- [ ] Create base service layer protocols
- [ ] Set up navigation infrastructure

### Phase 2: Authentication (Week 2-3)
- [ ] Email/password authentication
- [ ] Google Sign-In integration
- [ ] Sign in with Apple
- [ ] Facebook authentication
- [ ] Phone authentication (SMS)
- [ ] Password reset flow

### Phase 3: Core Features (Week 3-5)
- [ ] Home view with role-based routing
- [ ] Schedule list and detail views
- [ ] Schedule builder/create flow
- [ ] Employee management
- [ ] Profile settings

### Phase 4: Integrations (Week 5-6)
- [ ] RevenueCat subscription handling
- [ ] Push notifications (FCM)
- [ ] Intercom support chat
- [ ] Deep links
- [ ] Analytics events

### Phase 5: Polish (Week 6-7)
- [ ] Error handling and edge cases
- [ ] Loading states and empty views
- [ ] Accessibility
- [ ] UI animations and transitions
- [ ] Unit and UI tests

### Phase 6: Launch (Week 7-8)
- [ ] TestFlight beta testing
- [ ] App Store submission
- [ ] Migration documentation
- [ ] Feature parity verification

---

## High-Priority Screens

### Tier 1: Critical (Must Have for MVP)
1. **Login/Auth** - Entry point, required for all users
2. **Home** - Dashboard for both manager/worker roles
3. **Schedule List** - Core functionality
4. **Schedule Detail** - View individual schedules
5. **Role Selection** - Manager vs Worker routing

### Tier 2: Essential (Second Wave)
6. **Schedule Builder** - Create/edit schedules (manager)
7. **Employee List** - Manage team (manager)
8. **Profile Settings** - User preferences
9. **Onboarding** - First-time user experience

### Tier 3: Enhanced (Post-MVP)
10. Archived Schedules
11. Priorities Submission
12. Shift Change Requests
13. Gemini/Ask AI features
14. Calendar integration

---

## Technical Decisions

### Dependency Management
- **Swift Package Manager** (SPM) - Primary
- Avoid CocoaPods unless required for specific SDKs

### Minimum iOS Version
- **iOS 15.0+** - Enables modern SwiftUI features (async/await, NavigationStack)

### Architecture Pattern
- **MVVM** with Combine
- Protocol-oriented design for testability
- Dependency injection via initializers

### Testing Strategy
- **Unit Tests**: ViewModels, Services, Models
- **UI Tests**: Critical user flows
- **Snapshot Tests**: UI components (optional)

---

## Firebase Configuration

### GoogleService-Info.plist
- Per-flavor configuration files:
  - `GoogleService-Info-Dev.plist`
  - `GoogleService-Info-Staging.plist`
  - `GoogleService-Info-Production.plist`

### Initialization
```swift
// AppDelegate.swift
func application(_ application: UIApplication, 
                 didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?) -> Bool {
    FirebaseApp.configure()
    return true
}
```

---

## Security Considerations

1. **API Keys**: Never hardcode sensitive keys
2. **Keychain**: Store auth tokens securely
3. **App Check**: Enable Firebase App Check for production
4. **Certificate Pinning**: Consider for API calls
5. **Code Obfuscation**: Enable for release builds

---

## References

- [Firebase iOS SDK Documentation](https://firebase.google.com/docs/ios/setup)
- [SwiftUI App Lifecycle](https://developer.apple.com/documentation/swiftui/app)
- [Combine Framework](https://developer.apple.com/documentation/combine)
- [RevenueCat iOS SDK](https://www.revenuecat.com/docs/ios)
- [Intercom iOS SDK](https://developers.intercom.com/installing-intercom/docs/intercom-for-ios)

---

## Related Issues

- #1771 - Scheduler Native Platform Split
- #1843 - Flutter iOS to Native Swift Migration

## Related Repos

- [Scheduler](https://github.com/Scheduler-Systems/Scheduler) - Flutter monorepo
- [scheduler-contracts](https://github.com/Scheduler-Systems/scheduler-contracts) - API contracts
- [scheduler-api](https://github.com/Scheduler-Systems/scheduler-api) - Backend API
