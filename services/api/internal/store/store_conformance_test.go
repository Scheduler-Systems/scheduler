package store

import (
	"context"
	"fmt"
	"net/http"
	"os"
	"testing"
)

// demoProject is the emulator project id used by the Firestore-backed tests.
const demoProject = "demo-scheduler"

// runStoreConformance exercises the behavioural contract of a Store against an
// EMPTY store. It is run against both MemoryStore and (when the emulator is
// available) FirestoreStore so the two implementations stay in lock-step.
func runStoreConformance(t *testing.T, st Store) {
	t.Helper()
	const tid = "t1"

	// ---- schedules ----
	s1 := st.PutSchedule(Schedule{ID: "s1", TenantID: tid, Name: "Morning Shift", CreatedBy: "u1", CreatedAt: "2026-01-01T00:00:00Z"})
	if s1.UpdatedAt == "" {
		t.Error("PutSchedule should set UpdatedAt")
	}
	st.PutSchedule(Schedule{ID: "s2", TenantID: tid, Name: "Night", CreatedAt: "2026-01-02T00:00:00Z"})

	if got := st.GetSchedule(tid, "s1"); got == nil || got.Name != "Morning Shift" {
		t.Fatalf("GetSchedule(s1) = %+v, want Morning Shift", got)
	}
	if st.GetSchedule(tid, "nope") != nil {
		t.Error("GetSchedule(missing) should be nil")
	}
	if list := st.ListSchedules(tid); len(list) != 2 || list[0].ID != "s2" {
		t.Errorf("ListSchedules should be newest-first [s2,s1], got %+v", list)
	}
	if st.FindScheduleByName(tid, "  morning SHIFT ") == nil {
		t.Error("FindScheduleByName should be case-insensitive + trimmed")
	}
	if st.FindScheduleByName(tid, "absent") != nil {
		t.Error("FindScheduleByName(absent) should be nil")
	}
	// createdAt preserved, updatedAt refreshed on update.
	if upd := st.PutSchedule(Schedule{ID: "s1", TenantID: tid, Name: "Renamed", CreatedBy: "u1"}); upd.CreatedAt != "2026-01-01T00:00:00Z" {
		t.Errorf("PutSchedule update should preserve CreatedAt, got %q", upd.CreatedAt)
	}

	// ---- employees (embedded) ----
	if st.ListEmployees(tid, "missing") != nil {
		t.Error("ListEmployees(missing schedule) should be nil")
	}
	if empty := st.ListEmployees(tid, "s1"); empty == nil || len(empty) != 0 {
		t.Errorf("ListEmployees(no employees) should be non-nil empty, got %+v", empty)
	}
	if _, ok := st.PutEmployee(tid, "missing", Employee{Email: "a@x.com"}); ok {
		t.Error("PutEmployee(missing schedule) should return false")
	}
	st.PutEmployee(tid, "s1", Employee{Name: "Al", Email: "Al@x.com", UserRef: "u2"})
	st.PutEmployee(tid, "s1", Employee{Name: "Bo", Email: "bo@x.com"})
	// Replace by normalized email; order preserved (Al stays first). The whole
	// record is replaced, so the patch carries UserRef to keep the link.
	st.PutEmployee(tid, "s1", Employee{Name: "Al2", Email: " al@X.com ", UserRef: "u2"})
	el := st.ListEmployees(tid, "s1")
	if len(el) != 2 || el[0].Name != "Al2" || el[1].Name != "Bo" {
		t.Errorf("employee upsert should replace-in-place preserving order, got %+v", el)
	}
	if st.GetEmployee(tid, "s1", "AL@x.com") == nil {
		t.Error("GetEmployee should match on normalized email")
	}
	if !st.IsScheduleMember(tid, "s1", "u1") {
		t.Error("creator (created_by) should be a member")
	}
	if !st.IsScheduleMember(tid, "s1", "u2") {
		t.Error("linked employee (user_ref) should be a member")
	}
	if st.IsScheduleMember(tid, "s1", "stranger") {
		t.Error("non-member should not be a member")
	}
	if !st.RemoveEmployee(tid, "s1", "BO@x.com") {
		t.Error("RemoveEmployee should return true when removed")
	}
	if st.RemoveEmployee(tid, "s1", "gone@x.com") {
		t.Error("RemoveEmployee(absent) should return false")
	}
	if len(st.ListEmployees(tid, "s1")) != 1 {
		t.Error("one employee should remain after removal")
	}

	// ---- invitations ----
	st.PutInvitation(Invitation{ID: "i1", TenantID: tid, ScheduleID: "s1", CreatedAt: "2026-01-01T00:00:00Z"})
	st.PutInvitation(Invitation{ID: "i2", TenantID: tid, ScheduleID: "s1", CreatedAt: "2026-01-02T00:00:00Z"})
	st.PutInvitation(Invitation{ID: "i3", TenantID: tid, ScheduleID: "other", CreatedAt: "2026-01-03T00:00:00Z"})
	if st.GetInvitation(tid, "i1") == nil {
		t.Error("GetInvitation(i1) should exist")
	}
	if invs := st.ListInvitationsForSchedule(tid, "s1"); len(invs) != 2 || invs[0].ID != "i2" {
		t.Errorf("ListInvitationsForSchedule should be newest-first [i2,i1], got %+v", invs)
	}

	// ---- shift requests ----
	st.PutShiftRequest(ShiftRequest{ID: "r1", TenantID: tid, ScheduleID: "s1", CreatedAt: "2026-01-01T00:00:00Z"})
	if st.GetShiftRequest(tid, "r1") == nil {
		t.Error("GetShiftRequest(r1) should exist")
	}
	if len(st.ListShiftRequestsForSchedule(tid, "s1")) != 1 {
		t.Error("ListShiftRequestsForSchedule(s1) should have 1")
	}
	if !st.DeleteShiftRequest(tid, "r1") {
		t.Error("DeleteShiftRequest(r1) should return true")
	}
	if st.DeleteShiftRequest(tid, "r1") {
		t.Error("DeleteShiftRequest(already gone) should return false")
	}

	// ---- schedule-change requests ----
	st.PutScheduleChangeRequest(ScheduleChangeRequest{ID: "c1", TenantID: tid, ScheduleID: "s1"})
	if st.GetScheduleChangeRequest(tid, "c1") == nil {
		t.Error("GetScheduleChangeRequest(c1) should exist")
	}
	if len(st.ListScheduleChangeRequestsForSchedule(tid, "s1")) != 1 {
		t.Error("ListScheduleChangeRequestsForSchedule(s1) should have 1")
	}

	// ---- user profile merge semantics ----
	st.PutUserProfile(UserProfile{TenantID: tid, UID: "u1", Email: "u1@x.com", Role: "employer"})
	st.PutUserProfile(UserProfile{TenantID: tid, UID: "u1", DisplayName: "User One"}) // name-only patch
	if p := st.GetUserProfile(tid, "u1"); p == nil || p.Role != "employer" || p.DisplayName != "User One" || p.Email != "u1@x.com" {
		t.Errorf("name-only update should not clobber role/email, got %+v", p)
	}

	// ---- global-by-id entities ----
	st.PutAvailability(Availability{ID: "a1", TenantID: tid})
	if st.GetAvailability("a1") == nil {
		t.Error("GetAvailability(a1) should exist")
	}
	st.PutDraft(Draft{ID: "d1", TenantID: tid})
	if st.GetDraft("d1") == nil {
		t.Error("GetDraft(d1) should exist")
	}
	st.DeleteDraft("d1")
	if st.GetDraft("d1") != nil {
		t.Error("GetDraft after delete should be nil")
	}
	st.PutRequest(Request{ID: "rq1", TenantID: tid})
	if st.GetRequest("rq1") == nil {
		t.Error("GetRequest(rq1) should exist")
	}
	st.PutImport(Import{ImportID: "im1", TenantID: tid, CreatedAt: 1})
	st.PutImport(Import{ImportID: "im2", TenantID: tid, CreatedAt: 2})
	if st.GetImport("im1") == nil {
		t.Error("GetImport(im1) should exist")
	}
	if imps := st.ListImports(tid, 100); len(imps) != 2 || imps[0].ImportID != "im2" {
		t.Errorf("ListImports should be newest-first [im2,im1], got %+v", imps)
	}
	st.PutApproval(Approval{ID: "ap1", TenantID: tid}) // no getter; just must not panic
}

func TestMemoryStore_Conformance(t *testing.T) {
	runStoreConformance(t, NewMemoryStore())
}

// newEmulatorStore returns a Firestore store wired to the emulator, or skips the
// test when FIRESTORE_EMULATOR_HOST is unset (so plain `go test` stays green
// without an emulator). It clears the emulator first for a known-empty start.
func newEmulatorStore(t *testing.T) *FirestoreStore {
	t.Helper()
	if os.Getenv("FIRESTORE_EMULATOR_HOST") == "" {
		t.Skip("FIRESTORE_EMULATOR_HOST not set; skipping Firestore-backed test")
	}
	clearEmulator(t)
	st, err := NewFirestoreStore(context.Background(), demoProject)
	if err != nil {
		t.Fatalf("NewFirestoreStore: %v", err)
	}
	t.Cleanup(func() { _ = st.Close() })
	return st
}

// clearEmulator wipes all documents in the Firestore emulator for a clean slate.
func clearEmulator(t *testing.T) {
	t.Helper()
	host := os.Getenv("FIRESTORE_EMULATOR_HOST")
	url := fmt.Sprintf("http://%s/emulator/v1/projects/%s/databases/(default)/documents", host, demoProject)
	req, err := http.NewRequest(http.MethodDelete, url, nil)
	if err != nil {
		t.Fatalf("clearEmulator request: %v", err)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatalf("clearEmulator: %v (is the Firestore emulator running?)", err)
	}
	_ = resp.Body.Close()
}

func TestFirestoreStore_Conformance(t *testing.T) {
	st := newEmulatorStore(t)
	runStoreConformance(t, st)
}

// TestFirestoreStore_SurvivesReopen is the core Phase C guarantee: data written
// through one store instance is still there after the process "restarts" (a
// fresh client against the same backend).
func TestFirestoreStore_SurvivesReopen(t *testing.T) {
	if os.Getenv("FIRESTORE_EMULATOR_HOST") == "" {
		t.Skip("FIRESTORE_EMULATOR_HOST not set; skipping Firestore-backed test")
	}
	clearEmulator(t)
	ctx := context.Background()

	writer, err := NewFirestoreStore(ctx, demoProject)
	if err != nil {
		t.Fatalf("NewFirestoreStore(writer): %v", err)
	}
	writer.PutSchedule(Schedule{ID: "sx", TenantID: "tx", Name: "Persisted", CreatedBy: "u"})
	writer.PutEmployee("tx", "sx", Employee{Name: "Em", Email: "em@x.com", UserRef: "u9"})
	_ = writer.Close()

	reader, err := NewFirestoreStore(ctx, demoProject)
	if err != nil {
		t.Fatalf("NewFirestoreStore(reader): %v", err)
	}
	defer reader.Close()

	got := reader.GetSchedule("tx", "sx")
	if got == nil || got.Name != "Persisted" {
		t.Fatalf("schedule did not survive reopen: %+v", got)
	}
	if emps := reader.ListEmployees("tx", "sx"); len(emps) != 1 || emps[0].Email != "em@x.com" {
		t.Fatalf("employees did not survive reopen: %+v", emps)
	}
}
