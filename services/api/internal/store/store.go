// Package store defines the persistence interface and shared data model types
// used across all scheduler-api handlers.
package store

// Schedule represents a tenant-scoped scheduling configuration.
type Schedule struct {
	ID          string                 `json:"id"`
	TenantID    string                 `json:"tenantId"`
	Name        string                 `json:"name"`
	Settings    map[string]interface{} `json:"settings"`
	Status      string                 `json:"status"`
	CreatedBy   string                 `json:"createdBy,omitempty"`
	CreatedAt   string                 `json:"createdAt,omitempty"`
	UpdatedAt   string                 `json:"updatedAt,omitempty"`
	PublishedAt string                 `json:"publishedAt,omitempty"`
	PublishedBy string                 `json:"publishedBy,omitempty"`
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

	PutAvailability(e Availability) Availability
	GetAvailability(id string) *Availability

	PutDraft(d Draft) Draft
	GetDraft(id string) *Draft
	DeleteDraft(id string)

	PutRequest(r Request) Request
	GetRequest(id string) *Request

	PutImport(imp Import) Import
	GetImport(importID string) *Import
	ListImports(tenantID string, limit int) []Import

	PutApproval(a Approval) Approval
}
