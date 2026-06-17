# Scheduler Web - Next.js Architecture

Migration from Flutter Web to Next.js for the Scheduler native platform split.

## Overview

This document defines the architecture for migrating the Flutter Web app to Next.js 15 with App Router, targeting the manager and worker web experience.

## Flutter Web Analysis

### Pages/Routes (28 total)

#### Authentication
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/login` | `LoginEmailWidget` | Email/password login |
| `/create-account` | `CreateAccountEmailWidget` | Email registration |
| `/phone-signin` | `PhoneSignInView` | Phone auth (limited access) |
| `/phone-code` | `PhoneCodeWidget` | OTP verification |
| `/password-reset` | `PasswordResetWidget` | Password recovery |
| `/verify-email` | `VerifyEmailWaitingWidget` | Email verification |
| `/get-name` | `GetNameWidget` | Profile name setup |
| `/choose-role` | `ChooseRoleWidget` | Manager/Worker selection |

#### Main App
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/` | `HomeWidget` | Dashboard/landing |
| `/onboarding` | `OnboardingWidget` | First-time user flow |
| `/my-schedules` | `MySchedulesWidget` | Schedule list |
| `/schedule/:id` | `MainWidget` | Schedule dashboard |
| `/schedule/:id/build` | `ScheduleBuildWidget` | Build/edit schedule |
| `/schedule/:id/settings` | `ScheduleSettingsWidget` | Schedule configuration |
| `/schedule/:id/request` | `ScheduleRequestWidget` | Request time off |
| `/archived` | `ArchivedSchedulesWidget` | Archived schedules |

#### Employees
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/employees` | `EmployeeListWidget` | Employee management |
| `/employees/add` | `AddEmployeeWidget` | Add new employee |

#### Priorities
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/priorities` | `CurrentPrioritiesWidget` | View priorities |
| `/priorities/submit` | `PrioritiesSubmissionWidget` | Submit priorities |

#### Chat
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/chat` | `Chat2MainWidget` | Chat list |
| `/chat/:id` | `ChatThreadWidget` | Chat thread |
| `/chat/:id/details` | `Chat2DetailsWidget` | Chat details |

#### Other
| Route | Flutter Widget | Description |
|-------|---------------|-------------|
| `/profile` | `ProfileSettingsWidget` | User settings |
| `/gemini` | `GeminiScreenWidget` | AI assistant |
| `/export` | `ExportShiftsWidget` | Export shifts |
| `/share-pdf` | `SharePdfWidget` | PDF sharing |

### State Management (Flutter)

- **Provider** with `ChangeNotifier` (`FFAppState`)
- **RxDart** for reactive streams
- **Firebase Auth** user stream for auth state
- **PremiumStatusProvider** for subscription status

### Firebase Integrations

| Service | Usage |
|---------|-------|
| Firebase Auth | Email/password, Google, Apple, Facebook, Phone, Anonymous |
| Cloud Firestore | Primary database |
| Cloud Functions | Server-side logic |
| Firebase Storage | File uploads |
| Firebase Analytics | Event tracking |
| Firebase Crashlytics | Error reporting |
| Firebase Messaging | Push notifications |
| Remote Config | Feature flags |
| App Check | Security (mobile only) |

### Firestore Collections

```
users/
  - email, displayName, photoUrl, uid, role, isPremium, etc.

schedules/
  - scheduleName, employees[], currentPriorities[], scheduleSettings

built_schedules/
  - Generated schedule data

notifications/
  - User notifications

chats/
  - Chat rooms

chat_messages/
  - Individual messages

schedules_involved/
  - User-schedule relationships

shift_requests/
  - Time off requests

schedule_requests/
  - Schedule change requests

schedule_change_request/
  - Change request details

mail/
  - Email records
```

### Dependencies (Key)

- `go_router` - Navigation
- `google_sign_in` / `sign_in_with_apple` - Social auth
- `purchases_flutter` - RevenueCat subscriptions
- `google_generative_ai` - Gemini AI
- `device_calendar` - Calendar export
- `pdf` / `printing` - PDF generation
- `cached_network_image` - Image caching
- `flutter_animate` - Animations

### SEO Requirements

- Public landing page (marketing)
- Schedule share pages (public preview)
- Deep linking for schedule invitations
- Meta tags for social sharing

---

## Next.js Architecture

### Technology Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| Framework | Next.js 15 | App Router, RSC, SEO |
| Language | TypeScript | Type safety |
| State | Zustand + React Query | Simple global state, server state |
| Auth | Firebase JS SDK + next-firebase-auth-edge | SSR-compatible auth |
| Database | Firebase JS SDK | Direct Firestore access |
| Styling | Tailwind CSS | Utility-first, matches Flutter theming |
| Forms | React Hook Form + Zod | Type-safe validation |
| Animations | Framer Motion | Declarative animations |

### App Router Structure

```
app/
├── (auth)/                    # Auth layout group
│   ├── layout.tsx             # Auth shell (minimal UI)
│   ├── login/
│   │   └── page.tsx
│   ├── create-account/
│   │   └── page.tsx
│   ├── phone-signin/
│   │   └── page.tsx
│   ├── phone-code/
│   │   └── page.tsx
│   ├── password-reset/
│   │   └── page.tsx
│   ├── verify-email/
│   │   └── page.tsx
│   ├── get-name/
│   │   └── page.tsx
│   └── choose-role/
│       └── page.tsx
│
├── (main)/                    # Main app layout group
│   ├── layout.tsx             # App shell (nav, sidebar)
│   ├── page.tsx               # Dashboard (/)
│   ├── onboarding/
│   │   └── page.tsx
│   ├── my-schedules/
│   │   └── page.tsx
│   ├── schedule/[id]/
│   │   ├── page.tsx           # Schedule dashboard
│   │   ├── build/
│   │   │   └── page.tsx
│   │   ├── settings/
│   │   │   └── page.tsx
│   │   └── request/
│   │       └── page.tsx
│   ├── archived/
│   │   └── page.tsx
│   ├── employees/
│   │   ├── page.tsx
│   │   └── add/
│   │       └── page.tsx
│   ├── priorities/
│   │   ├── page.tsx
│   │   └── submit/
│   │       └── page.tsx
│   ├── chat/
│   │   ├── page.tsx
│   │   └── [id]/
│   │       ├── page.tsx
│   │       └── details/
│   │           └── page.tsx
│   ├── profile/
│   │   └── page.tsx
│   ├── gemini/
│   │   └── page.tsx
│   ├── export/
│   │   └── page.tsx
│   └── share-pdf/
│       └── page.tsx
│
├── (public)/                  # Public pages (no auth)
│   ├── layout.tsx
│   └── invite/[token]/
│       └── page.tsx           # Schedule invitation
│
├── api/                       # API routes
│   ├── auth/
│   │   └── [...nextauth]/     # Custom auth handlers
│   ├── webhooks/
│   │   └── revenuecat/        # Subscription webhooks
│   └── cron/
│       └── build-schedules/   # Scheduled builds
│
├── layout.tsx                 # Root layout
├── globals.css
├── not-found.tsx
└── error.tsx
```

### Directory Structure

```
scheduler-web/
├── app/                       # Next.js App Router
├── components/
│   ├── ui/                    # Base UI components
│   │   ├── button.tsx
│   │   ├── input.tsx
│   │   ├── dialog.tsx
│   │   ├── dropdown.tsx
│   │   └── ...
│   ├── auth/                  # Auth components
│   │   ├── auth-provider.tsx
│   │   ├── protected-route.tsx
│   │   └── social-buttons.tsx
│   ├── schedule/              # Schedule-specific
│   │   ├── schedule-card.tsx
│   │   ├── shift-calendar.tsx
│   │   ├── employee-list.tsx
│   │   └── priority-form.tsx
│   ├── chat/                  # Chat components
│   │   ├── chat-list.tsx
│   │   ├── message-bubble.tsx
│   │   └── chat-input.tsx
│   └── layout/                # Layout components
│       ├── sidebar.tsx
│       ├── header.tsx
│       ├── mobile-nav.tsx
│       └── footer.tsx
│
├── lib/
│   ├── firebase/
│   │   ├── client.ts          # Firebase client SDK
│   │   ├── server.ts          # Firebase Admin SDK
│   │   ├── auth.ts            # Auth utilities
│   │   └── firestore.ts       # Firestore helpers
│   ├── stores/
│   │   ├── app-store.ts       # Zustand store
│   │   └── premium-store.ts
│   ├── hooks/
│   │   ├── use-user.ts
│   │   ├── use-schedule.ts
│   │   ├── use-premium.ts
│   │   └── use-subscription.ts
│   ├── queries/
│   │   ├── schedules.ts       # React Query queries
│   │   ├── users.ts
│   │   └── chat.ts
│   ├── utils/
│   │   ├── format.ts
│   │   ├── validation.ts
│   │   └── date.ts
│   └── constants.ts
│
├── types/
│   ├── database.ts            # Firestore types
│   ├── schedule.ts
│   ├── user.ts
│   └── api.ts
│
├── styles/
│   └── globals.css            # Tailwind imports
│
├── public/
│   ├── fonts/
│   ├── images/
│   └── icons/
│
├── docs/
│   └── ARCHITECTURE.md
│
├── package.json
├── tsconfig.json
├── next.config.ts
├── tailwind.config.ts
└── firebase.json
```

### State Management

#### Zustand (Client State)
```typescript
// lib/stores/app-store.ts
interface AppState {
  currentScheduleId: string | null;
  sidebarOpen: boolean;
  onboardingStep: number;
  // Actions
  setCurrentSchedule: (id: string) => void;
  toggleSidebar: () => void;
}
```

#### React Query (Server State)
```typescript
// lib/queries/schedules.ts
export const scheduleKeys = {
  all: ['schedules'] as const,
  list: () => [...scheduleKeys.all, 'list'] as const,
  detail: (id: string) => [...scheduleKeys.all, 'detail', id] as const,
};

export const useSchedules = () => useQuery({
  queryKey: scheduleKeys.list(),
  queryFn: () => getScheduleList(),
});

export const useSchedule = (id: string) => useQuery({
  queryKey: scheduleKeys.detail(id),
  queryFn: () => getSchedule(id),
  enabled: !!id,
});
```

### Authentication Flow

1. **Login Page** → Firebase Auth signIn
2. **Middleware** → Verify session cookie
3. **Protected Routes** → Redirect to login if unauthenticated
4. **Server Components** → Access user via cookies

```typescript
// middleware.ts
export async function middleware(request: NextRequest) {
  const session = request.cookies.get('session');
  // Verify Firebase session cookie
  // Redirect to login if invalid
}
```

### React Server Components

| Component Type | Use Case |
|---------------|----------|
| Server Component | Static data fetching, SEO pages |
| Client Component | Interactive UI, event handlers |
| Server Action | Form submissions, mutations |

### Data Fetching Strategy

```
Server Components:
  - Initial page data (SSR/SSG)
  - SEO-critical content
  - Static data

Client Components:
  - Real-time subscriptions
  - Optimistic updates
  - Interactive features
```

---

## Migration Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] Initialize Next.js project with TypeScript
- [ ] Configure Tailwind CSS
- [ ] Set up Firebase JS SDK
- [ ] Create base UI components
- [ ] Implement authentication flow

### Phase 2: Core Pages (Week 3-4)
- [ ] Build auth pages (login, register, password-reset)
- [ ] Create main layout with navigation
- [ ] Implement dashboard page
- [ ] Build my-schedules page
- [ ] Set up protected routes

### Phase 3: Schedule Management (Week 5-6)
- [ ] Schedule dashboard page
- [ ] Schedule build/edit functionality
- [ ] Schedule settings page
- [ ] Employee management
- [ ] Priorities submission

### Phase 4: Communication (Week 7)
- [ ] Chat list page
- [ ] Chat thread with real-time messages
- [ ] Chat details/invite users

### Phase 5: Premium Features (Week 8)
- [ ] RevenueCat integration
- [ ] Subscription UI
- [ ] Premium feature gates
- [ ] Calendar export

### Phase 6: Polish & Migration (Week 9-10)
- [ ] Performance optimization
- [ ] SEO implementation
- [ ] Analytics integration
- [ ] Error tracking
- [ ] Gradual rollout with feature flags

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| App Router over Pages | Better SEO, RSC support, streaming |
| Zustand over Redux | Simpler, less boilerplate |
| React Query for server state | Built-in caching, optimistic updates |
| Firebase JS SDK | Maintain compatibility with existing backend |
| Tailwind CSS | Rapid development, matches Flutter theming |
| next-firebase-auth-edge | SSR-compatible Firebase auth |

## Boundary Constraints

Per platform rules:
- No direct production database writes outside APIs
- All routes must carry tenant identity
- Manager approval required for schedule mutations
- Agent-network only for delegated service tasks
