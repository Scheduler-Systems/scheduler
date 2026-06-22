package store

import (
	"sort"
	"strings"
	"sync"
	"time"
)

// MemoryStore is a thread-safe in-memory implementation of Store.
// It is the default store used during development and in tests.
type MemoryStore struct {
	mu                     sync.RWMutex
	schedules              map[string]Schedule              // key: "tenantID:scheduleID"
	employees              map[string][]Employee            // key: "tenantID:scheduleID" → ordered employees
	invitations            map[string]Invitation            // key: "tenantID:invitationID"
	shiftRequests          map[string]ShiftRequest          // key: "tenantID:requestID"
	scheduleChangeRequests map[string]ScheduleChangeRequest // key: "tenantID:requestID"
	userProfiles           map[string]UserProfile           // key: "tenantID:uid"
	availability           map[string]Availability
	notifications          map[string]Notification
	drafts                 map[string]Draft
	requests               map[string]Request
	imports                map[string]Import
	approvals              map[string]Approval
}

// NewMemoryStore returns an initialised MemoryStore.
func NewMemoryStore() *MemoryStore {
	return &MemoryStore{
		schedules:              make(map[string]Schedule),
		employees:              make(map[string][]Employee),
		invitations:            make(map[string]Invitation),
		shiftRequests:          make(map[string]ShiftRequest),
		scheduleChangeRequests: make(map[string]ScheduleChangeRequest),
		userProfiles:           make(map[string]UserProfile),
		availability:           make(map[string]Availability),
		notifications:          make(map[string]Notification),
		drafts:                 make(map[string]Draft),
		requests:               make(map[string]Request),
		imports:                make(map[string]Import),
		approvals:              make(map[string]Approval),
	}
}

// normalizeEmail trims and lower-cases an email so add/remove/dedup all treat
// "Bob@x.com", "bob@x.com", and " bob@x.com " as the same employee — matching
// scheduler-web's csv-employees normalization and the IDOR-fix note that the
// employees[] identity is the email.
func normalizeEmail(email string) string {
	return strings.ToLower(strings.TrimSpace(email))
}

// ListSchedules returns all schedules for a tenant, newest first.
func (m *MemoryStore) ListSchedules(tenantID string) []Schedule {
	m.mu.RLock()
	defer m.mu.RUnlock()

	var out []Schedule
	for _, s := range m.schedules {
		if s.TenantID == tenantID {
			out = append(out, s)
		}
	}
	// Sort descending by createdAt string (ISO-8601 lexicographic order is
	// identical to chronological order).
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	return out
}

// PutSchedule upserts a schedule, preserving createdAt on update and always
// refreshing updatedAt.
func (m *MemoryStore) PutSchedule(s Schedule) Schedule {
	m.mu.Lock()
	defer m.mu.Unlock()

	key := s.TenantID + ":" + s.ID
	now := time.Now().UTC().Format(time.RFC3339)

	if existing, ok := m.schedules[key]; ok {
		// Preserve original createdAt.
		if s.CreatedAt == "" {
			s.CreatedAt = existing.CreatedAt
		}
	} else {
		if s.CreatedAt == "" {
			s.CreatedAt = now
		}
	}
	s.UpdatedAt = now
	m.schedules[key] = s
	return s
}

// GetSchedule returns the schedule for a tenant/id pair, or nil.
func (m *MemoryStore) GetSchedule(tenantID, scheduleID string) *Schedule {
	m.mu.RLock()
	defer m.mu.RUnlock()

	s, ok := m.schedules[tenantID+":"+scheduleID]
	if !ok {
		return nil
	}
	cp := s
	return &cp
}

// FindScheduleByName returns the first schedule with the given name for a
// tenant, or nil if none exists. Used for duplicate-name detection.
//
// Matching is case-insensitive and ignores surrounding whitespace so the
// server is the single source of truth for what counts as a duplicate and
// agrees with the iOS, Android, and web clients (all of which treat
// "Morning Shift", "morning shift", and " Morning Shift " as the same name).
// The handler trims the stored name; this comparison folds case via
// strings.EqualFold and trims both sides defensively.
func (m *MemoryStore) FindScheduleByName(tenantID, name string) *Schedule {
	target := strings.TrimSpace(name)
	m.mu.RLock()
	defer m.mu.RUnlock()
	for _, s := range m.schedules {
		if s.TenantID == tenantID && strings.EqualFold(strings.TrimSpace(s.Name), target) {
			cp := s
			return &cp
		}
	}
	return nil
}

// DeleteSchedule removes a schedule; a no-op if it does not exist.
func (m *MemoryStore) DeleteSchedule(tenantID, scheduleID string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.schedules, tenantID+":"+scheduleID)
}

// PutAvailability stores an availability entry.
func (m *MemoryStore) PutAvailability(e Availability) Availability {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.availability[e.ID] = e
	return e
}

// GetAvailability returns an availability entry by id, or nil.
func (m *MemoryStore) GetAvailability(id string) *Availability {
	m.mu.RLock()
	defer m.mu.RUnlock()
	e, ok := m.availability[id]
	if !ok {
		return nil
	}
	cp := e
	return &cp
}

// PutNotification upserts a notification (keyed by ID).
func (m *MemoryStore) PutNotification(n Notification) Notification {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.notifications[n.ID] = n
	return n
}

// ListNotifications returns a recipient's notifications (tenant + userID), newest first.
func (m *MemoryStore) ListNotifications(tenantID, userID string) []Notification {
	m.mu.RLock()
	defer m.mu.RUnlock()
	out := []Notification{}
	for _, n := range m.notifications {
		if n.TenantID == tenantID && n.UserID == userID {
			out = append(out, n)
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

// PutDraft stores a draft.
func (m *MemoryStore) PutDraft(d Draft) Draft {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.drafts[d.ID] = d
	return d
}

// GetDraft returns a draft by id, or nil.
func (m *MemoryStore) GetDraft(id string) *Draft {
	m.mu.RLock()
	defer m.mu.RUnlock()
	d, ok := m.drafts[id]
	if !ok {
		return nil
	}
	cp := d
	return &cp
}

// DeleteDraft removes a draft; a no-op if it does not exist.
func (m *MemoryStore) DeleteDraft(id string) {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.drafts, id)
}

// PutRequest stores a request.
func (m *MemoryStore) PutRequest(r Request) Request {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.requests[r.ID] = r
	return r
}

// GetRequest returns a request by id, or nil.
func (m *MemoryStore) GetRequest(id string) *Request {
	m.mu.RLock()
	defer m.mu.RUnlock()
	r, ok := m.requests[id]
	if !ok {
		return nil
	}
	cp := r
	return &cp
}

// PutImport stores an import record.
func (m *MemoryStore) PutImport(imp Import) Import {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.imports[imp.ImportID] = imp
	return imp
}

// GetImport returns an import record by id, or nil.
func (m *MemoryStore) GetImport(importID string) *Import {
	m.mu.RLock()
	defer m.mu.RUnlock()
	imp, ok := m.imports[importID]
	if !ok {
		return nil
	}
	cp := imp
	return &cp
}

// ListImports returns up to limit imports for a tenant, sorted by createdAt
// descending (newest first). limit is capped at 100.
func (m *MemoryStore) ListImports(tenantID string, limit int) []Import {
	m.mu.RLock()
	defer m.mu.RUnlock()

	if limit > 100 {
		limit = 100
	}

	var out []Import
	for _, imp := range m.imports {
		if imp.TenantID == tenantID {
			out = append(out, imp)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	if len(out) > limit {
		out = out[:limit]
	}
	return out
}

// PutApproval stores an approval record.
func (m *MemoryStore) PutApproval(a Approval) Approval {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.approvals[a.ID] = a
	return a
}

// -------------------------------------------------------------------------
// Employees (embedded in the schedule)
// -------------------------------------------------------------------------

// scheduleExistsLocked reports whether a schedule exists. Callers must hold at
// least the read lock.
func (m *MemoryStore) scheduleExistsLocked(tenantID, scheduleID string) bool {
	_, ok := m.schedules[tenantID+":"+scheduleID]
	return ok
}

// ListEmployees returns the employees of a schedule, or nil if the schedule
// does not exist. An existing schedule with no employees returns a non-nil
// empty slice so handlers can tell "no schedule" (nil) from "no employees".
func (m *MemoryStore) ListEmployees(tenantID, scheduleID string) []Employee {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if !m.scheduleExistsLocked(tenantID, scheduleID) {
		return nil
	}
	src := m.employees[tenantID+":"+scheduleID]
	out := make([]Employee, len(src))
	copy(out, src)
	return out
}

// GetEmployee returns the employee with the given email (normalized) on a
// schedule, or nil if the schedule or employee does not exist.
func (m *MemoryStore) GetEmployee(tenantID, scheduleID, email string) *Employee {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if !m.scheduleExistsLocked(tenantID, scheduleID) {
		return nil
	}
	target := normalizeEmail(email)
	for _, e := range m.employees[tenantID+":"+scheduleID] {
		if normalizeEmail(e.Email) == target {
			cp := e
			return &cp
		}
	}
	return nil
}

// PutEmployee upserts an employee onto a schedule, keyed by normalized email.
// An existing employee with the same email is replaced in place (preserving
// list order); a new employee is appended. Returns false if the schedule does
// not exist.
func (m *MemoryStore) PutEmployee(tenantID, scheduleID string, e Employee) (Employee, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if !m.scheduleExistsLocked(tenantID, scheduleID) {
		return Employee{}, false
	}
	key := tenantID + ":" + scheduleID
	target := normalizeEmail(e.Email)
	list := m.employees[key]
	for i, existing := range list {
		if normalizeEmail(existing.Email) == target {
			list[i] = e
			m.employees[key] = list
			return e, true
		}
	}
	m.employees[key] = append(list, e)
	return e, true
}

// RemoveEmployee removes the employee with the given email (normalized) from a
// schedule. Returns true if an employee was removed.
func (m *MemoryStore) RemoveEmployee(tenantID, scheduleID, email string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	key := tenantID + ":" + scheduleID
	target := normalizeEmail(email)
	list := m.employees[key]
	for i, e := range list {
		if normalizeEmail(e.Email) == target {
			m.employees[key] = append(list[:i:i], list[i+1:]...)
			return true
		}
	}
	return false
}

// IsScheduleMember reports whether userID is the schedule creator (created_by)
// or an employee linked to it by user_ref uid. This is the Go-side analogue of
// the Firestore schedule_acl membership signal used by the IDOR fix: mutation
// of a schedule's employees is allowed only for members, never an arbitrary
// authenticated caller in the same tenant.
func (m *MemoryStore) IsScheduleMember(tenantID, scheduleID, userID string) bool {
	m.mu.RLock()
	defer m.mu.RUnlock()
	s, ok := m.schedules[tenantID+":"+scheduleID]
	if !ok {
		return false
	}
	if userID != "" && s.CreatedBy == userID {
		return true
	}
	for _, e := range m.employees[tenantID+":"+scheduleID] {
		if userID != "" && e.UserRef == userID {
			return true
		}
	}
	return false
}

// -------------------------------------------------------------------------
// Invitations (schedule_requests: add-employee / join workflow)
// -------------------------------------------------------------------------

// PutInvitation upserts an invitation record, keyed by tenant + id.
func (m *MemoryStore) PutInvitation(inv Invitation) Invitation {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.invitations[inv.TenantID+":"+inv.ID] = inv
	return inv
}

// GetInvitation returns an invitation by tenant + id, or nil.
func (m *MemoryStore) GetInvitation(tenantID, id string) *Invitation {
	m.mu.RLock()
	defer m.mu.RUnlock()
	inv, ok := m.invitations[tenantID+":"+id]
	if !ok {
		return nil
	}
	cp := inv
	return &cp
}

// ListInvitationsForSchedule returns all invitations targeting a schedule,
// newest first.
func (m *MemoryStore) ListInvitationsForSchedule(tenantID, scheduleID string) []Invitation {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var out []Invitation
	for _, inv := range m.invitations {
		if inv.TenantID == tenantID && inv.ScheduleID == scheduleID {
			out = append(out, inv)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	return out
}

// -------------------------------------------------------------------------
// Shift-swap requests (built_schedules/{bid}/shift_requests)
// -------------------------------------------------------------------------

// PutShiftRequest upserts a shift-swap request, keyed by tenant + id.
func (m *MemoryStore) PutShiftRequest(req ShiftRequest) ShiftRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.shiftRequests[req.TenantID+":"+req.ID] = req
	return req
}

// GetShiftRequest returns a shift-swap request by tenant + id, or nil.
func (m *MemoryStore) GetShiftRequest(tenantID, id string) *ShiftRequest {
	m.mu.RLock()
	defer m.mu.RUnlock()
	req, ok := m.shiftRequests[tenantID+":"+id]
	if !ok {
		return nil
	}
	cp := req
	return &cp
}

// ListShiftRequestsForSchedule returns all shift-swap requests targeting a
// schedule, newest first.
func (m *MemoryStore) ListShiftRequestsForSchedule(tenantID, scheduleID string) []ShiftRequest {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var out []ShiftRequest
	for _, req := range m.shiftRequests {
		if req.TenantID == tenantID && req.ScheduleID == scheduleID {
			out = append(out, req)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	return out
}

// DeleteShiftRequest removes a shift-swap request by tenant + id. Returns true
// if a request was removed.
func (m *MemoryStore) DeleteShiftRequest(tenantID, id string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	key := tenantID + ":" + id
	if _, ok := m.shiftRequests[key]; !ok {
		return false
	}
	delete(m.shiftRequests, key)
	return true
}

// -------------------------------------------------------------------------
// Schedule-change requests (scheduleChangeRequest)
// -------------------------------------------------------------------------

// PutScheduleChangeRequest upserts a schedule-change request, keyed by
// tenant + id.
func (m *MemoryStore) PutScheduleChangeRequest(req ScheduleChangeRequest) ScheduleChangeRequest {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.scheduleChangeRequests[req.TenantID+":"+req.ID] = req
	return req
}

// GetScheduleChangeRequest returns a schedule-change request by tenant + id,
// or nil.
func (m *MemoryStore) GetScheduleChangeRequest(tenantID, id string) *ScheduleChangeRequest {
	m.mu.RLock()
	defer m.mu.RUnlock()
	req, ok := m.scheduleChangeRequests[tenantID+":"+id]
	if !ok {
		return nil
	}
	cp := req
	return &cp
}

// ListScheduleChangeRequestsForSchedule returns all schedule-change requests
// targeting a schedule, newest first.
func (m *MemoryStore) ListScheduleChangeRequestsForSchedule(tenantID, scheduleID string) []ScheduleChangeRequest {
	m.mu.RLock()
	defer m.mu.RUnlock()
	var out []ScheduleChangeRequest
	for _, req := range m.scheduleChangeRequests {
		if req.TenantID == tenantID && req.ScheduleID == scheduleID {
			out = append(out, req)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		return out[i].CreatedAt > out[j].CreatedAt
	})
	return out
}

// -------------------------------------------------------------------------
// User profiles (users/{uid})
// -------------------------------------------------------------------------

// GetUserProfile returns the profile for (tenantID, uid), or nil if none has
// been written yet.
func (m *MemoryStore) GetUserProfile(tenantID, uid string) *UserProfile {
	m.mu.RLock()
	defer m.mu.RUnlock()
	p, ok := m.userProfiles[tenantID+":"+uid]
	if !ok {
		return nil
	}
	cp := p
	return &cp
}

// PutUserProfile upserts a profile with MERGE semantics, mirroring the web
// client's setDoc(..., { merge: true }): only non-zero patch fields overwrite
// the stored doc, so a name-only write does not clobber a previously chosen
// role (and vice-versa). LastActiveTime is always applied (every write bumps
// it). The (tenantID, uid) identity fields on the patch are authoritative and
// always set on the stored doc.
func (m *MemoryStore) PutUserProfile(patch UserProfile) UserProfile {
	m.mu.Lock()
	defer m.mu.Unlock()
	key := patch.TenantID + ":" + patch.UID

	// Start from the existing doc (if any) so unspecified fields are preserved.
	merged := m.userProfiles[key]

	// Identity is always authoritative on the patch.
	merged.TenantID = patch.TenantID
	merged.UID = patch.UID

	// Mergeable scalar fields: only a non-empty patch value overwrites.
	if patch.Email != "" {
		merged.Email = patch.Email
	}
	if patch.DisplayName != "" {
		merged.DisplayName = patch.DisplayName
	}
	if patch.Title != "" {
		merged.Title = patch.Title
	}
	if patch.Role != "" {
		merged.Role = patch.Role
	}
	// LastActiveTime is always bumped by the caller; apply it unconditionally so
	// a freshly written timestamp is never dropped.
	if patch.LastActiveTime != "" {
		merged.LastActiveTime = patch.LastActiveTime
	}

	m.userProfiles[key] = merged
	return merged
}
