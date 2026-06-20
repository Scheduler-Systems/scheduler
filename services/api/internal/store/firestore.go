package store

import (
	"context"
	"errors"
	"fmt"
	"log"
	"sort"
	"strings"
	"time"

	"cloud.google.com/go/firestore"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
)

// FirestoreStore is a Cloud Firestore implementation of Store. It persists the
// same data model the MemoryStore holds, so the Go API survives a restart.
//
// Layout (tenant-nested; tenancy comes from the verified token's tenant claim):
//
//	tenants/{tid}/schedules/{sid}                 — Schedule
//	tenants/{tid}/schedule_employees/{sid}        — { employees: [...] } sidecar,
//	                                                 kept separate from the
//	                                                 schedule doc so PutSchedule
//	                                                 can full-Set without
//	                                                 clobbering the roster
//	tenants/{tid}/invitations/{id}                — Invitation (schedule_requests)
//	tenants/{tid}/shift_requests/{id}             — ShiftRequest
//	tenants/{tid}/schedule_change_requests/{id}   — ScheduleChangeRequest
//	tenants/{tid}/user_profiles/{uid}             — UserProfile
//	availability/{id}  drafts/{id}  requests/{id}  imports/{id}  approvals/{id}
//	                                              — global-by-id entities (the
//	                                                Store interface keys these by
//	                                                id alone, not by tenant)
//
// This is the Go API's own representation — NOT the legacy flat client doc shape
// (schedules/{id} with schedule_name). Client compatibility is provided at the
// API/JSON boundary (handlers), not by identical Firestore storage; mixing the
// two would require the legacy ACL-maintainer infrastructure the open core does
// not ship.
//
// LIMITATION: the Store interface predates this backend and returns neither
// error nor context (it was written for an infallible in-memory map). Firestore
// I/O CAN fail, so failures are logged (with an "firestore-store:" prefix) and
// the method degrades to the same zero/nil result an empty store would give.
// Callers cannot currently distinguish "not found" from "backend error".
//
// CONSEQUENCE FOR WRITES (tracked must-fix — do not back paying-customer traffic
// until resolved): a Put* whose Firestore write fails still returns the input
// value, so handlers respond 2xx and the client treats an un-persisted write as
// durable — a silent, permanent loss (retry-on-error clients will not retry a
// 2xx). This is mitigated at startup by a readiness probe (NewFirestoreStore
// fails loud if the backend is unreachable or credentials/permissions are wrong,
// so a misconfigured deployment crashes at boot instead of dropping writes at
// runtime) — but it does NOT cover a backend that fails AFTER boot. The real fix,
// giving Store methods error returns so handlers can return 5xx, ripples through
// every handler and the memory store and is a tracked follow-up, intentionally
// out of scope here.
type FirestoreStore struct {
	cl *firestore.Client
}

// Firestore collection names.
const (
	colTenants               = "tenants"
	colSchedules             = "schedules"
	colScheduleEmployees     = "schedule_employees"
	colInvitations           = "invitations"
	colShiftRequests         = "shift_requests"
	colScheduleChangeReqs    = "schedule_change_requests"
	colUserProfiles          = "user_profiles"
	colAvailability          = "availability"
	colDrafts                = "drafts"
	colRequests              = "requests"
	colImports               = "imports"
	colApprovals             = "approvals"
	firestoreOpTimeout       = 10 * time.Second
	errScheduleMissingString = "schedule does not exist"
)

var errScheduleMissing = errors.New(errScheduleMissingString)

// NewFirestoreStore creates a Firestore-backed Store for the given project.
// When FIRESTORE_EMULATOR_HOST is set the client targets the emulator and needs
// no credentials; otherwise it uses Application Default Credentials.
func NewFirestoreStore(ctx context.Context, projectID string) (*FirestoreStore, error) {
	cl, err := firestore.NewClient(ctx, projectID)
	if err != nil {
		return nil, err
	}
	// Readiness probe. firestore.NewClient is lazy (it issues no RPC), so without
	// this a deployment can "start" against an unreachable or misconfigured
	// backend and then silently drop writes at runtime (see the LIMITATION note).
	// A bounded Get on a sentinel doc forces one round-trip: NotFound proves the
	// backend is reachable and credentials/permissions work; any transport or
	// permission error fails init so the process crashes at boot instead.
	pctx, cancel := context.WithTimeout(ctx, firestoreOpTimeout)
	defer cancel()
	if _, perr := cl.Collection("_healthz").Doc("_probe").Get(pctx); perr != nil && status.Code(perr) != codes.NotFound {
		_ = cl.Close()
		return nil, fmt.Errorf("firestore readiness probe failed (project %q unreachable or misconfigured): %w", projectID, perr)
	}
	return &FirestoreStore{cl: cl}, nil
}

// Close releases the underlying Firestore client.
func (f *FirestoreStore) Close() error {
	if f.cl == nil {
		return nil
	}
	return f.cl.Close()
}

// opCtx returns a bounded context for a single Firestore operation. The Store
// interface carries no context, so each call uses a fresh background context.
func opCtx() (context.Context, context.CancelFunc) {
	return context.WithTimeout(context.Background(), firestoreOpTimeout)
}

func logErr(op string, err error) {
	if err != nil {
		log.Printf("firestore-store: %s failed: %v", op, err)
	}
}

func isNotFound(err error) bool {
	return status.Code(err) == codes.NotFound
}

func nowRFC3339() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// --- path helpers ----------------------------------------------------------

func (f *FirestoreStore) tenantDoc(tid string) *firestore.DocumentRef {
	return f.cl.Collection(colTenants).Doc(tid)
}

func (f *FirestoreStore) schedulesCol(tid string) *firestore.CollectionRef {
	return f.tenantDoc(tid).Collection(colSchedules)
}

func (f *FirestoreStore) scheduleRef(tid, sid string) *firestore.DocumentRef {
	return f.schedulesCol(tid).Doc(sid)
}

func (f *FirestoreStore) employeesRef(tid, sid string) *firestore.DocumentRef {
	return f.tenantDoc(tid).Collection(colScheduleEmployees).Doc(sid)
}

// -------------------------------------------------------------------------
// Schedules
// -------------------------------------------------------------------------

func (f *FirestoreStore) ListSchedules(tenantID string) []Schedule {
	ctx, cancel := opCtx()
	defer cancel()

	snaps, err := f.schedulesCol(tenantID).Documents(ctx).GetAll()
	if err != nil {
		logErr("ListSchedules", err)
		return nil
	}
	var out []Schedule
	for _, snap := range snaps {
		var s Schedule
		if err := snap.DataTo(&s); err != nil {
			logErr("ListSchedules.DataTo", err)
			continue
		}
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

func (f *FirestoreStore) PutSchedule(s Schedule) Schedule {
	ctx, cancel := opCtx()
	defer cancel()

	ref := f.scheduleRef(s.TenantID, s.ID)
	now := nowRFC3339()
	if s.CreatedAt == "" {
		if snap, err := ref.Get(ctx); err == nil && snap.Exists() {
			var existing Schedule
			if err := snap.DataTo(&existing); err == nil {
				s.CreatedAt = existing.CreatedAt
			}
		}
		if s.CreatedAt == "" {
			s.CreatedAt = now
		}
	}
	s.UpdatedAt = now

	// Full Set is safe: the employee roster lives in a separate sidecar doc.
	if _, err := ref.Set(ctx, s); err != nil {
		logErr("PutSchedule", err)
	}
	return s
}

func (f *FirestoreStore) GetSchedule(tenantID, scheduleID string) *Schedule {
	ctx, cancel := opCtx()
	defer cancel()

	snap, err := f.scheduleRef(tenantID, scheduleID).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetSchedule", err)
		}
		return nil
	}
	var s Schedule
	if err := snap.DataTo(&s); err != nil {
		logErr("GetSchedule.DataTo", err)
		return nil
	}
	return &s
}

func (f *FirestoreStore) FindScheduleByName(tenantID, name string) *Schedule {
	target := strings.TrimSpace(name)
	for _, s := range f.ListSchedules(tenantID) {
		if strings.EqualFold(strings.TrimSpace(s.Name), target) {
			cp := s
			return &cp
		}
	}
	return nil
}

func (f *FirestoreStore) DeleteSchedule(tenantID, scheduleID string) {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.scheduleRef(tenantID, scheduleID).Delete(ctx); err != nil {
		logErr("DeleteSchedule", err)
	}
	// Best-effort cleanup of the employee sidecar.
	if _, err := f.employeesRef(tenantID, scheduleID).Delete(ctx); err != nil && !isNotFound(err) {
		logErr("DeleteSchedule.employees", err)
	}
}

// -------------------------------------------------------------------------
// Employees (a sidecar doc schedule_employees/{sid} holding an array, so the
// schedule doc can be full-Set without clobbering the roster)
// -------------------------------------------------------------------------

// employeesDoc is the shape of the schedule_employees/{sid} sidecar.
type employeesDoc struct {
	Employees []Employee `firestore:"employees"`
}

// scheduleExists reports whether the schedule doc exists (employees ops mirror
// the MemoryStore contract: nil/false when the parent schedule is absent).
func (f *FirestoreStore) scheduleExists(ctx context.Context, tenantID, scheduleID string) bool {
	snap, err := f.scheduleRef(tenantID, scheduleID).Get(ctx)
	if err != nil {
		return false
	}
	return snap.Exists()
}

func (f *FirestoreStore) ListEmployees(tenantID, scheduleID string) []Employee {
	ctx, cancel := opCtx()
	defer cancel()

	if !f.scheduleExists(ctx, tenantID, scheduleID) {
		return nil // schedule does not exist
	}
	snap, err := f.employeesRef(tenantID, scheduleID).Get(ctx)
	if err != nil {
		if isNotFound(err) {
			return []Employee{} // existing schedule, no roster yet
		}
		logErr("ListEmployees", err)
		return []Employee{}
	}
	var w employeesDoc
	if err := snap.DataTo(&w); err != nil {
		logErr("ListEmployees.DataTo", err)
		return []Employee{}
	}
	if w.Employees == nil {
		return []Employee{}
	}
	return w.Employees
}

func (f *FirestoreStore) GetEmployee(tenantID, scheduleID, email string) *Employee {
	target := normalizeEmail(email)
	for _, e := range f.ListEmployees(tenantID, scheduleID) {
		if normalizeEmail(e.Email) == target {
			cp := e
			return &cp
		}
	}
	return nil
}

// readEmployeesTx reads the employee sidecar inside a transaction, treating a
// missing sidecar as an empty roster. All tx reads must precede tx writes.
func readEmployeesTx(tx *firestore.Transaction, ref *firestore.DocumentRef) ([]Employee, error) {
	snap, err := tx.Get(ref)
	if err != nil {
		if isNotFound(err) {
			return nil, nil
		}
		return nil, err
	}
	var w employeesDoc
	if err := snap.DataTo(&w); err != nil {
		return nil, err
	}
	return w.Employees, nil
}

func (f *FirestoreStore) PutEmployee(tenantID, scheduleID string, e Employee) (Employee, bool) {
	ctx, cancel := opCtx()
	defer cancel()

	schedRef := f.scheduleRef(tenantID, scheduleID)
	empRef := f.employeesRef(tenantID, scheduleID)
	target := normalizeEmail(e.Email)
	err := f.cl.RunTransaction(ctx, func(ctx context.Context, tx *firestore.Transaction) error {
		// Reads first: parent must exist, then load the current roster.
		ssnap, err := tx.Get(schedRef)
		if err != nil {
			if isNotFound(err) {
				return errScheduleMissing
			}
			return err
		}
		if !ssnap.Exists() {
			return errScheduleMissing
		}
		list, err := readEmployeesTx(tx, empRef)
		if err != nil {
			return err
		}
		replaced := false
		for i, ex := range list {
			if normalizeEmail(ex.Email) == target {
				list[i] = e
				replaced = true
				break
			}
		}
		if !replaced {
			list = append(list, e)
		}
		return tx.Set(empRef, employeesDoc{Employees: list})
	})
	if err != nil {
		if !errors.Is(err, errScheduleMissing) {
			logErr("PutEmployee", err)
		}
		return Employee{}, false
	}
	return e, true
}

func (f *FirestoreStore) RemoveEmployee(tenantID, scheduleID, email string) bool {
	ctx, cancel := opCtx()
	defer cancel()

	empRef := f.employeesRef(tenantID, scheduleID)
	target := normalizeEmail(email)
	removed := false
	err := f.cl.RunTransaction(ctx, func(ctx context.Context, tx *firestore.Transaction) error {
		removed = false
		list, err := readEmployeesTx(tx, empRef)
		if err != nil {
			return err
		}
		out := make([]Employee, 0, len(list))
		for _, ex := range list {
			if normalizeEmail(ex.Email) == target {
				removed = true
				continue
			}
			out = append(out, ex)
		}
		if !removed {
			return nil
		}
		return tx.Set(empRef, employeesDoc{Employees: out})
	})
	if err != nil {
		logErr("RemoveEmployee", err)
		return false
	}
	return removed
}

func (f *FirestoreStore) IsScheduleMember(tenantID, scheduleID, userID string) bool {
	if userID == "" {
		return false
	}
	ctx, cancel := opCtx()
	defer cancel()

	ssnap, err := f.scheduleRef(tenantID, scheduleID).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("IsScheduleMember", err)
		}
		return false
	}
	var s Schedule
	if err := ssnap.DataTo(&s); err == nil && s.CreatedBy == userID {
		return true
	}
	esnap, err := f.employeesRef(tenantID, scheduleID).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("IsScheduleMember.employees", err)
		}
		return false
	}
	var w employeesDoc
	if err := esnap.DataTo(&w); err == nil {
		for _, e := range w.Employees {
			if e.UserRef == userID {
				return true
			}
		}
	}
	return false
}

// -------------------------------------------------------------------------
// Invitations (schedule_requests: add-employee / join workflow)
// -------------------------------------------------------------------------

func (f *FirestoreStore) PutInvitation(inv Invitation) Invitation {
	ctx, cancel := opCtx()
	defer cancel()
	ref := f.tenantDoc(inv.TenantID).Collection(colInvitations).Doc(inv.ID)
	if _, err := ref.Set(ctx, inv); err != nil {
		logErr("PutInvitation", err)
	}
	return inv
}

func (f *FirestoreStore) GetInvitation(tenantID, id string) *Invitation {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.tenantDoc(tenantID).Collection(colInvitations).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetInvitation", err)
		}
		return nil
	}
	var inv Invitation
	if err := snap.DataTo(&inv); err != nil {
		logErr("GetInvitation.DataTo", err)
		return nil
	}
	return &inv
}

func (f *FirestoreStore) ListInvitationsForSchedule(tenantID, scheduleID string) []Invitation {
	ctx, cancel := opCtx()
	defer cancel()
	snaps, err := f.tenantDoc(tenantID).Collection(colInvitations).
		Where("ScheduleID", "==", scheduleID).Documents(ctx).GetAll()
	if err != nil {
		logErr("ListInvitationsForSchedule", err)
		return nil
	}
	var out []Invitation
	for _, snap := range snaps {
		var inv Invitation
		if err := snap.DataTo(&inv); err != nil {
			logErr("ListInvitationsForSchedule.DataTo", err)
			continue
		}
		out = append(out, inv)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

// -------------------------------------------------------------------------
// Shift-swap requests
// -------------------------------------------------------------------------

func (f *FirestoreStore) PutShiftRequest(req ShiftRequest) ShiftRequest {
	ctx, cancel := opCtx()
	defer cancel()
	ref := f.tenantDoc(req.TenantID).Collection(colShiftRequests).Doc(req.ID)
	if _, err := ref.Set(ctx, req); err != nil {
		logErr("PutShiftRequest", err)
	}
	return req
}

func (f *FirestoreStore) GetShiftRequest(tenantID, id string) *ShiftRequest {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.tenantDoc(tenantID).Collection(colShiftRequests).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetShiftRequest", err)
		}
		return nil
	}
	var req ShiftRequest
	if err := snap.DataTo(&req); err != nil {
		logErr("GetShiftRequest.DataTo", err)
		return nil
	}
	return &req
}

func (f *FirestoreStore) ListShiftRequestsForSchedule(tenantID, scheduleID string) []ShiftRequest {
	ctx, cancel := opCtx()
	defer cancel()
	snaps, err := f.tenantDoc(tenantID).Collection(colShiftRequests).
		Where("ScheduleID", "==", scheduleID).Documents(ctx).GetAll()
	if err != nil {
		logErr("ListShiftRequestsForSchedule", err)
		return nil
	}
	var out []ShiftRequest
	for _, snap := range snaps {
		var req ShiftRequest
		if err := snap.DataTo(&req); err != nil {
			logErr("ListShiftRequestsForSchedule.DataTo", err)
			continue
		}
		out = append(out, req)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

func (f *FirestoreStore) DeleteShiftRequest(tenantID, id string) bool {
	ctx, cancel := opCtx()
	defer cancel()
	ref := f.tenantDoc(tenantID).Collection(colShiftRequests).Doc(id)
	if _, err := ref.Get(ctx); err != nil {
		if isNotFound(err) {
			return false
		}
		logErr("DeleteShiftRequest.Get", err)
		return false
	}
	if _, err := ref.Delete(ctx); err != nil {
		logErr("DeleteShiftRequest", err)
		return false
	}
	return true
}

// -------------------------------------------------------------------------
// Schedule-change requests
// -------------------------------------------------------------------------

func (f *FirestoreStore) PutScheduleChangeRequest(req ScheduleChangeRequest) ScheduleChangeRequest {
	ctx, cancel := opCtx()
	defer cancel()
	ref := f.tenantDoc(req.TenantID).Collection(colScheduleChangeReqs).Doc(req.ID)
	if _, err := ref.Set(ctx, req); err != nil {
		logErr("PutScheduleChangeRequest", err)
	}
	return req
}

func (f *FirestoreStore) GetScheduleChangeRequest(tenantID, id string) *ScheduleChangeRequest {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.tenantDoc(tenantID).Collection(colScheduleChangeReqs).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetScheduleChangeRequest", err)
		}
		return nil
	}
	var req ScheduleChangeRequest
	if err := snap.DataTo(&req); err != nil {
		logErr("GetScheduleChangeRequest.DataTo", err)
		return nil
	}
	return &req
}

func (f *FirestoreStore) ListScheduleChangeRequestsForSchedule(tenantID, scheduleID string) []ScheduleChangeRequest {
	ctx, cancel := opCtx()
	defer cancel()
	snaps, err := f.tenantDoc(tenantID).Collection(colScheduleChangeReqs).
		Where("ScheduleID", "==", scheduleID).Documents(ctx).GetAll()
	if err != nil {
		logErr("ListScheduleChangeRequestsForSchedule", err)
		return nil
	}
	var out []ScheduleChangeRequest
	for _, snap := range snaps {
		var req ScheduleChangeRequest
		if err := snap.DataTo(&req); err != nil {
			logErr("ListScheduleChangeRequestsForSchedule.DataTo", err)
			continue
		}
		out = append(out, req)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	return out
}

// -------------------------------------------------------------------------
// User profiles (merge semantics)
// -------------------------------------------------------------------------

func (f *FirestoreStore) GetUserProfile(tenantID, uid string) *UserProfile {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.tenantDoc(tenantID).Collection(colUserProfiles).Doc(uid).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetUserProfile", err)
		}
		return nil
	}
	var p UserProfile
	if err := snap.DataTo(&p); err != nil {
		logErr("GetUserProfile.DataTo", err)
		return nil
	}
	return &p
}

func (f *FirestoreStore) PutUserProfile(patch UserProfile) UserProfile {
	ctx, cancel := opCtx()
	defer cancel()

	ref := f.tenantDoc(patch.TenantID).Collection(colUserProfiles).Doc(patch.UID)
	merged := patch
	err := f.cl.RunTransaction(ctx, func(ctx context.Context, tx *firestore.Transaction) error {
		snap, err := tx.Get(ref)
		if err != nil && !isNotFound(err) {
			return err
		}
		var cur UserProfile
		if err == nil && snap.Exists() {
			if derr := snap.DataTo(&cur); derr != nil {
				return derr
			}
		}
		// Identity is always authoritative on the patch.
		cur.TenantID = patch.TenantID
		cur.UID = patch.UID
		// Mergeable scalars: only a non-empty patch value overwrites.
		if patch.Email != "" {
			cur.Email = patch.Email
		}
		if patch.DisplayName != "" {
			cur.DisplayName = patch.DisplayName
		}
		if patch.Title != "" {
			cur.Title = patch.Title
		}
		if patch.Role != "" {
			cur.Role = patch.Role
		}
		if patch.LastActiveTime != "" {
			cur.LastActiveTime = patch.LastActiveTime
		}
		merged = cur
		return tx.Set(ref, cur)
	})
	if err != nil {
		logErr("PutUserProfile", err)
	}
	return merged
}

// -------------------------------------------------------------------------
// Global-by-id entities (Store keys these by id alone, not by tenant)
// -------------------------------------------------------------------------

func (f *FirestoreStore) PutAvailability(e Availability) Availability {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colAvailability).Doc(e.ID).Set(ctx, e); err != nil {
		logErr("PutAvailability", err)
	}
	return e
}

func (f *FirestoreStore) GetAvailability(id string) *Availability {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.cl.Collection(colAvailability).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetAvailability", err)
		}
		return nil
	}
	var e Availability
	if err := snap.DataTo(&e); err != nil {
		logErr("GetAvailability.DataTo", err)
		return nil
	}
	return &e
}

func (f *FirestoreStore) PutDraft(d Draft) Draft {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colDrafts).Doc(d.ID).Set(ctx, d); err != nil {
		logErr("PutDraft", err)
	}
	return d
}

func (f *FirestoreStore) GetDraft(id string) *Draft {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.cl.Collection(colDrafts).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetDraft", err)
		}
		return nil
	}
	var d Draft
	if err := snap.DataTo(&d); err != nil {
		logErr("GetDraft.DataTo", err)
		return nil
	}
	return &d
}

func (f *FirestoreStore) DeleteDraft(id string) {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colDrafts).Doc(id).Delete(ctx); err != nil {
		logErr("DeleteDraft", err)
	}
}

func (f *FirestoreStore) PutRequest(r Request) Request {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colRequests).Doc(r.ID).Set(ctx, r); err != nil {
		logErr("PutRequest", err)
	}
	return r
}

func (f *FirestoreStore) GetRequest(id string) *Request {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.cl.Collection(colRequests).Doc(id).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetRequest", err)
		}
		return nil
	}
	var r Request
	if err := snap.DataTo(&r); err != nil {
		logErr("GetRequest.DataTo", err)
		return nil
	}
	return &r
}

func (f *FirestoreStore) PutImport(imp Import) Import {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colImports).Doc(imp.ImportID).Set(ctx, imp); err != nil {
		logErr("PutImport", err)
	}
	return imp
}

func (f *FirestoreStore) GetImport(importID string) *Import {
	ctx, cancel := opCtx()
	defer cancel()
	snap, err := f.cl.Collection(colImports).Doc(importID).Get(ctx)
	if err != nil {
		if !isNotFound(err) {
			logErr("GetImport", err)
		}
		return nil
	}
	var imp Import
	if err := snap.DataTo(&imp); err != nil {
		logErr("GetImport.DataTo", err)
		return nil
	}
	return &imp
}

func (f *FirestoreStore) ListImports(tenantID string, limit int) []Import {
	ctx, cancel := opCtx()
	defer cancel()
	if limit > 100 {
		limit = 100
	}
	snaps, err := f.cl.Collection(colImports).Where("TenantID", "==", tenantID).Documents(ctx).GetAll()
	if err != nil {
		logErr("ListImports", err)
		return nil
	}
	var out []Import
	for _, snap := range snaps {
		var imp Import
		if err := snap.DataTo(&imp); err != nil {
			logErr("ListImports.DataTo", err)
			continue
		}
		out = append(out, imp)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].CreatedAt > out[j].CreatedAt })
	if len(out) > limit {
		out = out[:limit]
	}
	return out
}

func (f *FirestoreStore) PutApproval(a Approval) Approval {
	ctx, cancel := opCtx()
	defer cancel()
	if _, err := f.cl.Collection(colApprovals).Doc(a.ID).Set(ctx, a); err != nil {
		logErr("PutApproval", err)
	}
	return a
}

// Compile-time assurance that *FirestoreStore satisfies Store.
var _ Store = (*FirestoreStore)(nil)
