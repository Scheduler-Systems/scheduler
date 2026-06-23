// Package store defines the persistence interface and shared data model types
// used across all scheduler-api handlers.
package store

// Schedule represents a tenant-scoped scheduling configuration.
type Schedule struct {
	ID       string                 `json:"id"`
	TenantID string                 `json:"tenantId"`
	Name     string                 `json:"name"`
	Settings map[string]interface{} `json:"settings"`
	Status   string                 `json:"status"`
	// CurrentPriorities is the ordered list of employee priority slots (by display
	// name) that employees submit against. Snake_case on the wire to match the
	// iOS/Android clients and the web's Firestore "current_priorities" field.
	CurrentPriorities []string `json:"current_priorities,omitempty"`
	CreatedBy         string   `json:"createdBy,omitempty"`
	CreatedAt         string   `json:"createdAt,omitempty"`
	UpdatedAt         string   `json:"updatedAt,omitempty"`
	PublishedAt       string   `json:"publishedAt,omitempty"`
	PublishedBy       string   `json:"publishedBy,omitempty"`
}

// Availability is a submitted availability entry for a schedule.
type Availability struct {
	ID           string                 `json:"id"`
	TenantID     string                 `json:"tenantId"`
	ScheduleID   string                 `json:"scheduleId"`
	UserID       string                 `json:"userId"`
	Availability map[string]interface{} `json:"availability"`
	State        string                 `json:"state"`
	CreatedAt    string                 `json:"createdAt"`
}

// Notification is a user-facing notification (chat, schedule request/change, system).
// Keyed globally by ID; listed per (tenant, recipient user), newest first.
type Notification struct {
	ID        string `json:"id"`
	TenantID  string `json:"tenantId"`
	UserID    string `json:"userId"` // recipient
	FromUser  string `json:"fromUser,omitempty"`
	Content   string `json:"content"`
	Type      string `json:"type"` // CHAT_MESSAGE|SCHEDULE_REQUEST|SCHEDULE_CHANGE|SHIFT_CHANGE|SYSTEM
	ChatRefID string `json:"chatRefId,omitempty"`
	IsRead    bool   `json:"isRead"`
	CreatedAt string `json:"createdAt,omitempty"`
}

// Draft is a schedule draft containing proposed shifts.
type Draft struct {
	ID         string        `json:"id"`
	TenantID   string        `json:"tenantId"`
	ScheduleID string        `json:"scheduleId"`
	Shifts     []interface{} `json:"shifts"`
	CreatedBy  string        `json:"createdBy"`
	CreatedAt  string        `json:"createdAt"`
}

// Request is a schedule-related request submitted by an actor.
type Request struct {
	ID         string                 `json:"id"`
	TenantID   string                 `json:"tenantId"`
	ScheduleID string                 `json:"scheduleId"`
	UserID     string                 `json:"userId"`
	Type       string                 `json:"type"`
	Details    map[string]interface{} `json:"details"`
	State      string                 `json:"state"`
	CreatedAt  string                 `json:"createdAt"`
}

// UserProfile mirrors the web/Flutter users/{uid} document written by
// scheduler-web lib/firestore-write.ts upsertUserProfile / upsertUserRole.
//
// The field names and the role encoding are VERBATIM matches for the Firestore
// doc so a profile written through this API round-trips with the existing
// web/iOS/Android clients:
//
//   - UID / Email          — identity, set on every write.
//   - DisplayName / Title  — the name-step fields.
//   - Role                 — the FLUTTER ROLE STRING, not a struct: exactly one
//     of "employer" or "employee" (see RoleEmployer /
//     RoleEmployee). The web client derives this via
//     roleStructToFlutterString(role) =
//     is_admin||is_creator ? "employer" : "employee".
//   - LastActiveTime       — RFC3339 timestamp; the web doc uses
//     serverTimestamp() under the key "last_active_time".
//
// UserProfile is tenant-scoped in the Go API (key tenantId+uid) so that
// cross-tenant identity collisions are impossible even though the Firestore
// collection is flat (users/{uid}); TenantID is carried but NOT serialized into
// the user-facing doc body (it is a routing/storage concern, json:"-").
type UserProfile struct {
	TenantID       string `json:"-"`
	UID            string `json:"uid"`
	Email          string `json:"email"`
	DisplayName    string `json:"display_name"`
	Title          string `json:"title"`
	Role           string `json:"role,omitempty"`
	LastActiveTime string `json:"last_active_time,omitempty"`
}

// Flutter role-string constants (the only valid values for UserProfile.Role).
// These mirror scheduler-web roleStructToFlutterString output VERBATIM — the
// server is authoritative for the role, but the wire encoding must stay byte
// identical so clients keep parsing it.
const (
	RoleEmployer = "employer"
	RoleEmployee = "employee"
)

// ShiftRequest mirrors the web/Flutter ShiftRequestsRecord document stored at
// the Firestore subcollection
// `schedules/{sid}/built_schedules/{bid}/shift_requests/{id}` (see
// scheduler-web lib/requests-types.ts ShiftRequest and lib/requests.ts
// createShiftRequest/updateShiftRequestStatus/deleteShiftRequest).
//
// The Firestore JSON keys are preserved VERBATIM — including the Flutter typo
// `reuqesting_employee` (should be "requesting_employee") and the
// `shift_request_status` enum values PENDING/ACCEPTED/"REJECETED" (the
// metathesis typo is faithful to Flutter) — so data written by this API
// round-trips with the existing iOS/Android/web clients.
//
// DocumentReference fields are represented as plain uid / id strings rather
// than Firestore refs so the Go API stays storage-agnostic:
//   - reuqesting_employee: the requester's uid (Flutter stores a users/{uid} ref)
//   - built_schedule_ref:  the built-schedule id (Flutter stores the doc ref)
//
// Timestamps round-trip as RFC3339 strings (Flutter stores Firestore
// Timestamps; the web layer converts to/from Date).
type ShiftRequest struct {
	ID                 string `json:"id"`
	TenantID           string `json:"tenantId"`
	ScheduleID         string `json:"scheduleId"`
	BuiltScheduleID    string `json:"builtScheduleId"`
	RequestingEmployee string `json:"reuqesting_employee"`
	ShiftToChangeFrom  string `json:"shift_to_change_from"`
	ShiftToChangeTo    string `json:"shift_to_change_to"`
	BuiltScheduleRef   string `json:"built_schedule_ref"`
	Status             string `json:"shift_request_status"`
	// Audit fields the web layer adds on review (Flutter ignores unknown fields).
	ReviewerUID string `json:"reviewer_uid,omitempty"`
	ReviewedAt  string `json:"reviewed_at,omitempty"`
	CreatedAt   string `json:"created_time,omitempty"`
}

// BuiltSchedule is a persisted, published shift grid — the canonical artifact
// schedule-build produces and that export-shifts / share-pdf / shift-swap
// requests consume. It mirrors the web/Flutter `schedules/{sid}/built_schedules/{bid}`
// document; the JSON keys are kept VERBATIM with the web (lib/types.ts BuiltSchedule)
// and the native clients so a grid persisted through this API round-trips with them.
//
// Grid shape: `Schedule` is a 3-D `[][][]string` matching the native assigner
// output (Android ShiftAssigner.assignShifts → List<List<List<String?>>>): the
// outer list is the period (weeks/rows), the middle the day/slot, the inner the
// assigned employee identifiers for that cell. The native assigner's "no
// assignment" null is normalized to "" on save (Go strings are not nullable, and
// an empty cell renders identically for export/share-pdf), so the inner type is a
// plain string. The web's Firestore representation wraps the inner list as
// `{stringList: [...]}` (Firestore can't nest arrays); that wrapping is a
// Firestore-storage concern handled in the firestore Store impl, NOT part of this
// API's wire shape (the native clients read this clean 3-D form from the Go API).
type BuiltSchedule struct {
	ID                   string       `json:"id"`
	TenantID             string       `json:"tenantId"`
	ScheduleID           string       `json:"scheduleId"`
	Grid                 [][][]string `json:"schedule"`
	FirstWeekday         string       `json:"first_weekday,omitempty"`
	LastWeekday          string       `json:"last_weekday,omitempty"`
	FirstWeekdayDateTime string       `json:"first_weekday_datetime,omitempty"`
	LastWeekdayDateTime  string       `json:"last_weekday_datetime,omitempty"`
	CurrentPriorities    []string     `json:"current_priorities"`
	TimeCreated          string       `json:"time_created,omitempty"`
	CreatedBy            string       `json:"createdBy,omitempty"`
}

// ScheduleChangeRequest mirrors the web/Flutter ScheduleChangeRequestRecord
// document stored at the Firestore collection `scheduleChangeRequest/{id}`
// (note camelCase collection name — see scheduler-web lib/requests-types.ts
// ScheduleChangeRequest and lib/requests.ts createScheduleChangeRequest /
// updateScheduleChangeRequestStatus).
//
// The Firestore JSON keys are preserved VERBATIM, including the CAPITALISED
// FlutterFlow-generated field names `DateTime` and `Reason`. `userId` is a
// plain uid string (not a ref), matching Flutter. `status` is a free-text
// string — Flutter has no typed enum here — with the conventional values
// "sent" (on create), "accepted" / "declined" (on review). `scheduleId` is a
// web-added field (Flutter ignores it) used to filter per-schedule.
type ScheduleChangeRequest struct {
	ID         string `json:"id"`
	TenantID   string `json:"tenantId"`
	ScheduleID string `json:"scheduleId"`
	DateTime   string `json:"DateTime"`
	Reason     string `json:"Reason"`
	UserID     string `json:"userId"`
	Status     string `json:"status"`
	// Audit fields the web layer adds on review (Flutter ignores unknown fields).
	ReviewerUID string `json:"reviewer_uid,omitempty"`
	ResolvedAt  string `json:"resolved_at,omitempty"`
	CreatedAt   string `json:"created_time,omitempty"`
}

// RoleStruct mirrors the web/Flutter EmployeeDetails.role shape
// (is_creator / is_admin / is_worker). It is server-authoritative: the role an
// employee is stored with determines what the membership ACL grants.
type RoleStruct struct {
	IsCreator bool `json:"is_creator"`
	IsAdmin   bool `json:"is_admin"`
	IsWorker  bool `json:"is_worker"`
}

// Employee mirrors the web/Flutter EmployeeDetails document embedded in the
// schedules/{id}.employees[] array. user_ref is represented as a plain uid
// string (or "" when the invitee has not yet linked an account) rather than a
// Firestore DocumentReference, so the Go API stays storage-agnostic.
//
// Identity for add/remove/dedup is the employee email, normalized (trimmed +
// lower-cased) — matching scheduler-web's csv-employees + addEmployee paths and
// the IDOR-fix note that "employees[] identity is the email".
type Employee struct {
	Name    string     `json:"employee_name"`
	Email   string     `json:"employee_email"`
	Phone   string     `json:"employee_phone"`
	Role    RoleStruct `json:"role"`
	UserRef string     `json:"user_ref,omitempty"`
}

// Invitation mirrors the web/Flutter schedule_requests/{id} document for the
// add-employee (manager invites) and join (employee asks) workflows.
//
// Status uses the Flutter enum string values verbatim — including the preserved
// typo "ADD_RQUEST_PENDING" — so data written here round-trips with the
// existing clients (see scheduler-web lib/requests-types.ts).
type Invitation struct {
	ID                   string `json:"id"`
	TenantID             string `json:"tenantId"`
	ScheduleID           string `json:"scheduleId"`
	ScheduleName         string `json:"scheduleName,omitempty"`
	IsAddRequest         bool   `json:"isAddRequest"`
	IsJoinRequest        bool   `json:"isJoinRequest"`
	FromUserID           string `json:"fromUserId"`
	ToUserID             string `json:"toUserId,omitempty"`
	ToUserIdentification string `json:"toUserIdentification"`
	Status               string `json:"status"`
	CreatedAt            string `json:"createdAt"`
	ReviewedBy           string `json:"reviewedBy,omitempty"`
	ReviewedAt           string `json:"reviewedAt,omitempty"`
}

// Import records the result of a schedgy approved-constraints import.
type Import struct {
	ImportID              string                 `json:"importId"`
	TenantID              string                 `json:"tenantId"`
	SourceSystem          string                 `json:"sourceSystem,omitempty"`
	ImportedConstraintIDs []string               `json:"importedConstraintIds"`
	TotalConstraints      int                    `json:"totalConstraints,omitempty"`
	ImportedCount         int                    `json:"importedCount,omitempty"`
	Metadata              map[string]interface{} `json:"metadata,omitempty"`
	CreatedBy             string                 `json:"createdBy,omitempty"`
	CreatedAt             int64                  `json:"createdAt,omitempty"`
}

// Approval tracks the review state for an import or availability submission.
type Approval struct {
	ID                  string `json:"id"`
	TenantID            string `json:"tenantId"`
	ImportID            string `json:"importId,omitempty"`
	State               string `json:"state"`
	ConstraintsReviewed int    `json:"constraintsReviewed,omitempty"`
	CreatedAt           string `json:"createdAt,omitempty"`
}

// Store is the persistence interface used by all route handlers.
// The in-memory implementation lives in memory.go; a Firestore implementation
// can be added later by satisfying this interface.
type Store interface {
	ListSchedules(tenantID string) []Schedule
	PutSchedule(s Schedule) Schedule
	GetSchedule(tenantID, scheduleID string) *Schedule
	DeleteSchedule(tenantID, scheduleID string)

	// FindScheduleByName returns the first schedule with the given name for a
	// tenant, or nil if none exists. Used for duplicate-name detection.
	FindScheduleByName(tenantID, name string) *Schedule

	// ---- Employees (embedded in the schedule, like schedules/{id}.employees[]) --

	// ListEmployees returns the employees of a schedule, or nil if the schedule
	// does not exist. An empty (but existing) schedule returns a non-nil empty
	// slice so handlers can distinguish "no schedule" (nil) from "no employees".
	ListEmployees(tenantID, scheduleID string) []Employee

	// GetEmployee returns the employee with the given (normalized) email on a
	// schedule, or nil if the schedule or employee does not exist.
	GetEmployee(tenantID, scheduleID, email string) *Employee

	// PutEmployee upserts an employee onto a schedule, keyed by normalized
	// email. Returns the stored employee and true, or false if the schedule
	// does not exist.
	PutEmployee(tenantID, scheduleID string, e Employee) (Employee, bool)

	// RemoveEmployee removes the employee with the given (normalized) email from
	// a schedule. Returns true if an employee was removed, false otherwise.
	RemoveEmployee(tenantID, scheduleID, email string) bool

	// IsScheduleMember reports whether userID is the schedule creator or an
	// employee linked to it (by user_ref uid). This is the Go-side analogue of
	// the Firestore schedule_acl membership signal used by the IDOR fix.
	IsScheduleMember(tenantID, scheduleID, userID string) bool

	// ---- Invitations (schedule_requests: add-employee / join workflow) --------

	PutInvitation(inv Invitation) Invitation
	GetInvitation(tenantID, id string) *Invitation
	ListInvitationsForSchedule(tenantID, scheduleID string) []Invitation

	// ---- Built schedules (the published shift grid) ---------------------------

	// PutBuiltSchedule upserts a built schedule (the persisted grid), keyed by
	// tenant + id. Returns the stored value.
	PutBuiltSchedule(b BuiltSchedule) BuiltSchedule

	// GetBuiltSchedule returns a built schedule by tenant + id, or nil.
	GetBuiltSchedule(tenantID, id string) *BuiltSchedule

	// ListBuiltSchedulesForSchedule returns the built schedules for a schedule,
	// newest first (by TimeCreated).
	ListBuiltSchedulesForSchedule(tenantID, scheduleID string) []BuiltSchedule

	// GetLatestBuiltSchedule returns the most recently created built schedule for
	// a schedule, or nil if none exists.
	GetLatestBuiltSchedule(tenantID, scheduleID string) *BuiltSchedule

	// ---- Requests: shift-swap (built_schedules/{bid}/shift_requests) ----------

	// PutShiftRequest upserts a shift-swap request, keyed by tenant + id.
	PutShiftRequest(req ShiftRequest) ShiftRequest

	// GetShiftRequest returns a shift-swap request by tenant + id, or nil.
	GetShiftRequest(tenantID, id string) *ShiftRequest

	// ListShiftRequestsForSchedule returns the shift-swap requests targeting a
	// schedule, newest first.
	ListShiftRequestsForSchedule(tenantID, scheduleID string) []ShiftRequest

	// DeleteShiftRequest removes a shift-swap request by tenant + id. Returns
	// true if a request was removed.
	DeleteShiftRequest(tenantID, id string) bool

	// ---- Requests: schedule-change (scheduleChangeRequest) --------------------

	// PutScheduleChangeRequest upserts a schedule-change request, keyed by
	// tenant + id.
	PutScheduleChangeRequest(req ScheduleChangeRequest) ScheduleChangeRequest

	// GetScheduleChangeRequest returns a schedule-change request by tenant + id,
	// or nil.
	GetScheduleChangeRequest(tenantID, id string) *ScheduleChangeRequest

	// ListScheduleChangeRequestsForSchedule returns the schedule-change requests
	// targeting a schedule, newest first.
	ListScheduleChangeRequestsForSchedule(tenantID, scheduleID string) []ScheduleChangeRequest

	PutAvailability(e Availability) Availability
	GetAvailability(id string) *Availability

	// PutNotification upserts a notification. ListNotifications returns a recipient's
	// notifications (tenant + userID), newest first.
	PutNotification(n Notification) Notification
	ListNotifications(tenantID, userID string) []Notification

	PutDraft(d Draft) Draft
	GetDraft(id string) *Draft
	DeleteDraft(id string)

	PutRequest(r Request) Request
	GetRequest(id string) *Request

	PutImport(imp Import) Import
	GetImport(importID string) *Import
	ListImports(tenantID string, limit int) []Import

	PutApproval(a Approval) Approval

	// ---- User profiles (users/{uid} document) ---------------------------------

	// GetUserProfile returns the profile for (tenantID, uid), or nil if none
	// exists yet.
	GetUserProfile(tenantID, uid string) *UserProfile

	// PutUserProfile upserts a user profile with MERGE semantics: only the
	// non-zero fields of the supplied patch overwrite the stored doc, mirroring
	// the web client's setDoc(..., { merge: true }). A first write for a uid
	// creates the doc. Returns the resulting stored profile.
	//
	// Merge rules (per field):
	//   - UID / Email / DisplayName / Title — overwritten when the patch value
	//     is non-empty; an empty string in the patch leaves the stored value
	//     untouched (a profile-name write must not clobber a previously set
	//     role/email, and a role-only write must not clobber the name).
	//   - Role — overwritten only when non-empty (so upsertUserRole sets role
	//     without touching name/title, and upsertUserProfile without a role does
	//     not wipe a role chosen on the earlier Choose-Role step).
	//   - LastActiveTime — always overwritten (every write bumps it).
	PutUserProfile(patch UserProfile) UserProfile
}
