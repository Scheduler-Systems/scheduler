# Flutter to Native Kotlin Migration Architecture

## Executive Summary

This document outlines the migration strategy from Flutter to native Kotlin/Compose for the Scheduler Android application. The migration prioritizes feature parity, performance, and maintainability while leveraging modern Android development practices.

---

## 1. Flutter App Analysis

### 1.1 Screens (35+ routes)

#### Authentication & Onboarding (Priority: P0)
| Screen | Route | Description |
|--------|-------|-------------|
| PhoneSignInView | `/phoneSignIn` | Phone authentication entry |
| PhoneCodeWidget | `/phoneCode` | SMS verification code |
| LoginEmailWidget | `/loginEmail` | Email login |
| CreateAccountEmailWidget | `/createAccountEmail` | Email registration |
| PasswordResetWidget | `/passwordReset` | Password recovery |
| VerifyEmailWaitingWidget | `/verifyEmailWaiting` | Email verification |
| GetNameWidget | `/getName` | User name collection |
| ChooseRoleWidget | `/chooseRole` | Role selection (employer/employee) |
| OnboardingView | `/onboarding` | First-time user tutorial |

#### Core Features (Priority: P0)
| Screen | Route | Description |
|--------|-------|-------------|
| HomeWidget | `/home` | Main dashboard |
| MySchedulesWidget | `/mySchedules` | Schedule list |
| NewSchedule1Widget | `/newSchedule1` | Schedule creation step 1 |
| NewSchedule2Widget | `/newSchedule2` | Schedule creation step 2 |
| ScheduleSettingsWidget | `/scheduleSettings` | Schedule configuration |
| ScheduleBuildWidget | `/scheduleBuild` | Build/manipulate schedule |
| ArchivedSchedulesWidget | `/archivedSchedules` | Archived schedules |

#### Employee Management (Priority: P1)
| Screen | Route | Description |
|--------|-------|-------------|
| EmployeeListWidget | `/employeeList` | Employee roster |
| AddEmployeeWidget | `/addEmployee` | Add new employee |

#### Priorities & Requests (Priority: P1)
| Screen | Route | Description |
|--------|-------|-------------|
| PrioritiesSubmissionWidget | `/prioritiesSubmission` | Submit availability |
| CurrentPrioritiesWidget | `/currentPriorities` | View priorities |
| ScheduleRequestWidget | `/scheduleRequest` | Schedule requests |
| ShiftChangeRequestsWidget | `/shiftChangeRequests` | Shift swap requests |

#### Communication (Priority: P2)
| Screen | Route | Description |
|--------|-------|-------------|
| Chat2MainWidget | `/chat2Main` | Chat list |
| Chat2DetailsWidget | `/chat2Details` | Chat conversation |
| Chat2InviteUsersWidget | `/chat2InviteUsers` | Invite to chat |
| ImageDetailsWidget | `/imageDetails` | Image viewer |

#### Export & Sharing (Priority: P2)
| Screen | Route | Description |
|--------|-------|-------------|
| ExportShiftsWidget | `/exportShifts` | Export options |
| SharePdfWidget | `/sharePdf` | PDF sharing |

#### Settings & Profile (Priority: P1)
| Screen | Route | Description |
|--------|-------|-------------|
| ProfileSettingsWidget | `/profileSettings` | User settings |

#### AI Features (Priority: P2)
| Screen | Route | Description |
|--------|-------|-------------|
| GeminiScreenWidget | `/geminiScreen` | AI assistance |

### 1.2 State Management

**Current Pattern:** FlutterFlow Model + Provider + ChangeNotifier

```
lib/
├── flutter_flow/flutter_flow_model.dart     # Base model class
├── features/*/view_models/                   # MVVM ViewModels
├── features/*/models/                        # UI state models
├── providers/premium_status_provider.dart    # Global state
└── app_state.dart                            # App-wide state
```

**Key Providers:**
- `PremiumStatusProvider` - Subscription/premium status
- `FFAppState` - App-wide persisted state
- `AppStateNotifier` - Auth state management

### 1.3 Firebase Integrations

| Service | Package | Usage |
|---------|---------|-------|
| Firebase Core | `firebase_core` | Initialization |
| Firebase Auth | `firebase_auth` | Phone, Email, Google, Apple auth |
| Cloud Firestore | `cloud_firestore` | Primary database |
| Cloud Functions | `cloud_functions` | Server-side logic |
| Firebase Storage | `firebase_storage` | File uploads |
| Firebase Messaging | `firebase_messaging` | Push notifications |
| Firebase Analytics | `firebase_analytics` | User analytics |
| Firebase Crashlytics | `firebase_crashlytics` | Crash reporting |
| Firebase Remote Config | `firebase_remote_config` | Feature flags |
| Firebase Performance | `firebase_performance` | Performance monitoring |
| Firebase App Check | `firebase_app_check` | App attestation |
| Firebase In-App Messaging | `firebase_in_app_messaging` | In-app campaigns |

### 1.4 Platform Channels

| Channel | Purpose |
|---------|---------|
| `secure_intercom` | Intercom SDK integration (Android) |
| `secure_intercom_ios` | Intercom SDK integration (iOS) |
| `segfault_prevention` | Native crash prevention |

### 1.5 Key Dependencies

#### Authentication
- `google_sign_in` - Google OAuth
- `sign_in_with_apple` - Apple OAuth
- `flutter_facebook_auth` - Facebook OAuth

#### Monetization
- `purchases_flutter` - RevenueCat subscriptions
- `purchases_ui_flutter` - RevenueCat UI

#### Analytics & Attribution
- `flutter_branch_sdk` - Branch deep links
- `intercom_flutter` - Customer support
- `google_generative_ai` - Gemini AI

#### UI Components
- `go_router` - Navigation (12.x)
- `table_calendar` - Calendar widget
- `pdf` + `printing` - PDF generation
- `cached_network_image` - Image caching
- `flutter_animate` - Animations

#### Device Integration
- `device_calendar` - Calendar export
- `permission_handler` - Permissions
- `image_picker` - Photo selection
- `file_picker` - File selection

---

## 2. Native Kotlin Architecture

### 2.1 App Structure

```
app/src/main/java/com/schedulersystems/scheduler/
├── SchedulerApplication.kt           # Application class, DI setup
├── MainActivity.kt                   # Single Activity
│
├── navigation/
│   ├── NavigationGraph.kt            # Compose Navigation graph
│   └── Screen.kt                     # Screen sealed class
│
├── ui/
│   ├── theme/
│   │   ├── Theme.kt                  # Material3 theme
│   │   ├── Color.kt                  # Color palette
│   │   └── Type.kt                   # Typography
│   │
│   ├── components/                   # Shared UI components
│   │   ├── SchedulerButton.kt
│   │   ├── SchedulerTextField.kt
│   │   ├── LoadingIndicator.kt
│   │   └── ...
│   │
│   └── screens/
│       ├── auth/
│       │   ├── phone/
│       │   │   ├── PhoneSignInScreen.kt
│       │   │   ├── PhoneSignInViewModel.kt
│       │   │   └── PhoneSignInState.kt
│       │   ├── email/
│       │   └── onboarding/
│       │
│       ├── home/
│       │   ├── HomeScreen.kt
│       │   ├── HomeViewModel.kt
│       │   └── HomeState.kt
│       │
│       ├── schedules/
│       │   ├── list/
│       │   ├── create/
│       │   ├── build/
│       │   └── settings/
│       │
│       ├── employees/
│       ├── priorities/
│       ├── chat/
│       ├── export/
│       └── profile/
│
├── viewmodels/                       # (Alternative: ViewModels in screens)
│
├── models/
│   ├── domain/                       # Domain models
│   │   ├── Schedule.kt
│   │   ├── Employee.kt
│   │   ├── Shift.kt
│   │   └── User.kt
│   │
│   └── ui/                           # UI state models
│       ├── ScheduleUiState.kt
│       └── EmployeeUiState.kt
│
├── data/
│   ├── remote/
│   │   ├── FirestoreService.kt
│   │   ├── FunctionsService.kt
│   │   └── StorageService.kt
│   │
│   ├── local/
│   │   ├── DataStoreManager.kt
│   │   └── CacheManager.kt
│   │
│   └── repositories/
│       ├── AuthRepository.kt
│       ├── ScheduleRepository.kt
│       ├── EmployeeRepository.kt
│       └── ChatRepository.kt
│
├── domain/
│   ├── usecases/
│   │   ├── CreateScheduleUseCase.kt
│   │   ├── SubmitPrioritiesUseCase.kt
│   │   └── ExportScheduleUseCase.kt
│   │
│   └── contracts/
│       └── ScheduleContracts.kt      # From scheduler-contracts
│
├── services/
│   ├── FirebaseService.kt
│   ├── NotificationService.kt
│   ├── RevenueCatService.kt
│   ├── BranchService.kt
│   └── IntercomService.kt
│
├── di/
│   ├── AppModule.kt
│   ├── NetworkModule.kt
│   └── FirebaseModule.kt
│
└── utils/
    ├── DateTimeUtils.kt
    ├── StringUtils.kt
    └── Extensions.kt
```

### 2.2 Architecture Pattern: MVVM + Clean Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         UI Layer                                 │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │   Composable    │───▶│   ViewModel     │                    │
│  │   (Screen)      │◀───│   (StateFlow)   │                    │
│  └─────────────────┘    └────────┬────────┘                    │
└──────────────────────────────────┼──────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────┐
│                         Domain Layer                             │
│  ┌─────────────────┐    ┌────────▼────────┐                    │
│  │   Use Case      │◀───│   Repository    │                    │
│  │                 │    │   (Interface)   │                    │
│  └─────────────────┘    └────────┬────────┘                    │
└──────────────────────────────────┼──────────────────────────────┘
                                   │
┌──────────────────────────────────┼──────────────────────────────┐
│                          Data Layer                              │
│  ┌─────────────────┐    ┌────────▼────────┐    ┌─────────────┐ │
│  │   Repository    │◀───│   Data Source   │◀───│  Firebase   │ │
│  │   (Impl)        │    │                 │    │  Firestore  │ │
│  └─────────────────┘    └─────────────────┘    └─────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Key Technologies

| Category | Technology | Purpose |
|----------|------------|---------|
| UI | Jetpack Compose | Declarative UI |
| Navigation | Navigation Compose | Type-safe navigation |
| State | StateFlow + ViewModel | Reactive state management |
| DI | Hilt | Dependency injection |
| Async | Kotlin Coroutines + Flow | Asynchronous operations |
| Database | Firebase Firestore | Cloud database |
| Auth | Firebase Auth | Authentication |
| Storage | Firebase Storage | File storage |
| Analytics | Firebase Analytics | User tracking |
| Crashlytics | Firebase Crashlytics | Crash reporting |
| Messaging | Firebase Cloud Messaging | Push notifications |
| Subscriptions | RevenueCat Android SDK | In-app purchases |
| Deep Links | Branch Android SDK | Attribution |
| Support | Intercom Android SDK | Customer support |
| AI | Google AI Client SDK | Gemini integration |

### 2.4 Data Models (Kotlin)

```kotlin
// Domain Models
data class Schedule(
    val id: String,
    val name: String,
    val tenantId: String,
    val employees: List<Employee>,
    val currentPriorities: List<String>,
    val settings: ScheduleSettings,
    val nextSchedule: List<ShiftRow>,
    val createdAt: Instant,
    val updatedAt: Instant
)

data class Employee(
    val id: String,
    val name: String,
    val email: String?,
    val phone: String?,
    val role: Role,
    val priorityMap: Map<String, Int>
)

data class Shift(
    val day: String,
    val startTime: LocalTime,
    val endTime: LocalTime,
    val assignedWorker: String?
)

data class ScheduleSettings(
    val submissionDeadline: SubmissionDeadline?,
    val enabledShifts: EnabledShifts,
    val timezone: String
)

// UI State Models
data class HomeUiState(
    val isLoading: Boolean = false,
    val schedules: List<Schedule> = emptyList(),
    val error: String? = null,
    val userRole: Role? = null
)

data class ScheduleBuildUiState(
    val schedule: Schedule? = null,
    val shiftRows: List<ShiftRow> = emptyList(),
    val isSaving: Boolean = false,
    val selectedCell: Pair<Int, Int>? = null
)
```

### 2.5 Navigation Structure

```kotlin
// navigation/Screen.kt
sealed class Screen(val route: String) {
    // Auth Flow
    object PhoneSignIn : Screen("phoneSignIn")
    object PhoneCode : Screen("phoneCode")
    object EmailLogin : Screen("loginEmail")
    object CreateAccount : Screen("createAccountEmail")
    object PasswordReset : Screen("passwordReset")
    object VerifyEmail : Screen("verifyEmailWaiting")
    object GetName : Screen("getName")
    object ChooseRole : Screen("chooseRole")
    object Onboarding : Screen("onboarding")
    
    // Main Flow
    object Home : Screen("home")
    object MySchedules : Screen("mySchedules")
    object NewSchedule1 : Screen("newSchedule1")
    object NewSchedule2 : Screen("newSchedule2?scheduleName={scheduleName}")
    object ScheduleSettings : Screen("scheduleSettings/{scheduleId}")
    object ScheduleBuild : Screen("scheduleBuild/{scheduleId}")
    object ArchivedSchedules : Screen("archivedSchedules/{scheduleId}")
    
    // Employees
    object EmployeeList : Screen("employeeList/{scheduleName}")
    object AddEmployee : Screen("addEmployee")
    
    // Priorities
    object PrioritiesSubmission : Screen("prioritiesSubmission/{scheduleId}")
    object CurrentPriorities : Screen("currentPriorities/{scheduleId}")
    object ScheduleRequest : Screen("scheduleRequest/{requestId}")
    object ShiftChangeRequests : Screen("shiftChangeRequests")
    
    // Chat
    object ChatMain : Screen("chat2Main")
    object ChatDetails : Screen("chat2Details/{chatId}")
    object ChatInvite : Screen("chat2InviteUsers")
    
    // Export
    object ExportShifts : Screen("exportShifts/{scheduleId}")
    object SharePdf : Screen("sharePdf/{scheduleId}")
    
    // Profile
    object ProfileSettings : Screen("profileSettings")
    
    // AI
    object Gemini : Screen("geminiScreen?scheduleName={scheduleName}")
}
```

---

## 3. Migration Roadmap

### Phase 1: Foundation (Weeks 1-2)
- [x] Create skeleton project structure
- [ ] Set up Gradle build with Kotlin DSL
- [ ] Configure Hilt DI
- [ ] Implement Material3 theme
- [ ] Create base UI components
- [ ] Set up Firebase project

### Phase 2: Authentication (Weeks 3-4)
- [ ] Phone authentication
- [ ] SMS verification
- [ ] Email authentication
- [ ] Google Sign-In
- [ ] Apple Sign-In
- [ ] Auth state management
- [ ] Onboarding flow

### Phase 3: Core Features (Weeks 5-8)
- [ ] Home screen
- [ ] Schedule list
- [ ] Schedule creation (Step 1 & 2)
- [ ] Schedule settings
- [ ] Schedule build
- [ ] Archived schedules

### Phase 4: Employee Management (Weeks 9-10)
- [ ] Employee list
- [ ] Add employee
- [ ] Employee details

### Phase 5: Priorities & Requests (Weeks 11-12)
- [ ] Priorities submission
- [ ] Current priorities
- [ ] Schedule requests
- [ ] Shift change requests

### Phase 6: Communication (Weeks 13-14)
- [ ] Chat list
- [ ] Chat conversation
- [ ] Image viewer
- [ ] Invite users

### Phase 7: Export & Sharing (Weeks 15-16)
- [ ] Export shifts
- [ ] PDF generation
- [ ] Share functionality

### Phase 8: AI & Premium (Weeks 17-18)
- [ ] Gemini integration
- [ ] RevenueCat subscriptions
- [ ] Premium features

### Phase 9: Polish & Testing (Weeks 19-20)
- [ ] UI polish
- [ ] Performance optimization
- [ ] Unit tests
- [ ] Integration tests
- [ ] UAT

---

## 4. Priority Screens

### P0 - Must Have (MVP)
1. PhoneSignInView - Authentication entry point
2. PhoneCodeWidget - SMS verification
3. HomeWidget - Main dashboard
4. MySchedulesWidget - Schedule list
5. NewSchedule1Widget - Schedule creation
6. NewSchedule2Widget - Schedule creation
7. ScheduleBuildWidget - Schedule manipulation
8. GetNameWidget - User setup
9. ChooseRoleWidget - Role selection

### P1 - High Priority
1. ScheduleSettingsWidget
2. EmployeeListWidget
3. AddEmployeeWidget
4. PrioritiesSubmissionWidget
5. CurrentPrioritiesWidget
6. ProfileSettingsWidget
7. ArchivedSchedulesWidget

### P2 - Medium Priority
1. Chat2MainWidget
2. Chat2DetailsWidget
3. ExportShiftsWidget
4. SharePdfWidget
5. GeminiScreenWidget
6. ScheduleRequestWidget

---

## 5. Firebase Configuration

### 5.1 Firestore Collections

| Collection | Document Model |
|------------|----------------|
| `users` | UsersRecord |
| `schedules` | SchedulesRecord |
| `schedules_involved` | SchedulesInvolvedRecord |
| `built_schedules` | BuiltSchedulesRecord |
| `schedule_requests` | ScheduleRequestsRecord |
| `shift_requests` | ShiftRequestsRecord |
| `chats` | ChatsRecord |
| `chat_messages` | ChatMessagesRecord |
| `notifications` | NotificationsRecord |
| `mail` | MailRecord |

### 5.2 Security Rules
- All collections require authentication
- Tenant-based access control via `tenantId`
- Role-based permissions (employer/employee)

---

## 6. Build Configuration

### 6.1 Gradle Dependencies

```kotlin
// Core
implementation("androidx.core:core-ktx:1.15.0")
implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
implementation("androidx.activity:activity-compose:1.9.3")

// Compose
implementation(platform("androidx.compose:compose-bom:2024.12.01"))
implementation("androidx.compose.ui:ui")
implementation("androidx.compose.material3:material3")
implementation("androidx.compose.ui:ui-tooling-preview")

// Navigation
implementation("androidx.navigation:navigation-compose:2.8.5")

// Firebase
implementation(platform("com.google.firebase:firebase-bom:33.7.0"))
implementation("com.google.firebase:firebase-auth")
implementation("com.google.firebase:firebase-firestore")
implementation("com.google.firebase:firebase-storage")
implementation("com.google.firebase:firebase-messaging")
implementation("com.google.firebase:firebase-analytics")
implementation("com.google.firebase:firebase-crashlytics")
implementation("com.google.firebase:firebase-config")
implementation("com.google.firebase:firebase-inappmessaging-display")

// Hilt
implementation("com.google.dagger:hilt-android:2.52")
kapt("com.google.dagger:hilt-compiler:2.52")
implementation("androidx.hilt:hilt-navigation-compose:1.2.0")

// Coroutines
implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

// RevenueCat
implementation("com.revenuecat.purchases:purchases:8.10.0")

// Google Sign-In
implementation("com.google.android.gms:play-services-auth:21.3.0")

// Branch
implementation("io.branch.sdk.android:library:6.1.0")

// Intercom
implementation("io.intercom.android:intercom-sdk:15.7.0")

// Gemini AI
implementation("com.google.ai.client.generativeai:generativeai:0.9.0")

// Image Loading
implementation("io.coil-kt:coil-compose:2.7.0")

// PDF
implementation("com.itextpdf:itext7-core:8.0.5")
```

---

## 7. Testing Strategy

### 7.1 Unit Tests
- ViewModel logic
- Repository implementations
- Use cases
- Utility functions

### 7.2 Integration Tests
- Firebase operations
- Authentication flows
- Navigation

### 7.3 UI Tests
- Compose UI testing
- Espresso for legacy views

---

## 8. Rollout Strategy

### 8.1 Parallel Deployment
- Maintain Flutter app in production
- Deploy native app to beta testers
- Gradual rollout via Play Store

### 8.2 Feature Flags
- Use Firebase Remote Config
- A/B test critical flows
- Gradual feature migration

### 8.3 Monitoring
- Firebase Crashlytics for crash tracking
- Firebase Performance for performance monitoring
- Analytics for user behavior

---

## 9. Success Criteria

- [ ] Feature parity with Flutter app
- [ ] Performance improvements (startup time, memory)
- [ ] Crash-free rate > 99.5%
- [ ] User satisfaction maintained
- [ ] Maintainable codebase with tests

---

## Appendix A: Flutter to Kotlin Mapping

| Flutter Widget | Kotlin Compose |
|----------------|----------------|
| `Scaffold` | `Scaffold` |
| `AppBar` | `TopAppBar` |
| `BottomNavigationBar` | `NavigationBar` |
| `ListView` | `LazyColumn` |
| `GridView` | `LazyVerticalGrid` |
| `TextField` | `OutlinedTextField` |
| `ElevatedButton` | `Button` |
| `TextButton` | `TextButton` |
| `IconButton` | `IconButton` |
| `CircularProgressIndicator` | `CircularProgressIndicator` |
| `AlertDialog` | `AlertDialog` |
| `BottomSheet` | `ModalBottomSheet` |
| `TabBar` | `TabRow` |
| `PageView` | `HorizontalPager` |
