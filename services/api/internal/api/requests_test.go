package api_test

// requests_test.go exercises the requests domain end-to-end through the router:
// shift-swap requests (create/list/get/patch-status/delete) and schedule-change
// requests (create/list/get/patch-status). It reuses the helpers (do, jsonBody,
// assertStatus, *Headers, mergeHeaders, deleteKey) defined in api_test.go.
//
// The membership ACL is the load-bearing security property here: a caller with
// valid tenant auth who is NOT a member of a schedule must NOT be able to read
// or mutate that schedule's requests (404 schedule_not_found before the ACL,
// then 403 not_a_schedule_member). On this base membership == schedule creator,
// so the seed helpers set CreatedBy accordingly.

import (
	"net/http"
	"testing"

	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

const (
	reqTenant = "tenant_security_demo"
	reqSched  = "sched_req_1"
)

// seedScheduleCreatedBy creates a schedule whose creator uid is `creator`, so
// that uid is a member and passes the IsScheduleMember ACL check.
func seedScheduleCreatedBy(st store.Store, creator string) {
	st.PutSchedule(store.Schedule{
		ID:        reqSched,
		TenantID:  reqTenant,
		Name:      "Requests Roster",
		Settings:  map[string]interface{}{},
		Status:    "published",
		CreatedBy: creator,
	})
}

// seedManagerSchedule creates a schedule owned by the manager header uid
// (user_mgr_1), so the manager is a member.
func seedManagerSchedule(st store.Store) { seedScheduleCreatedBy(st, "user_mgr_1") }

// seedWorkerSchedule creates a schedule owned by the worker/employee header uid
// (user_worker_1), so the employee is a member and can create requests, while a
// manager (different uid) is NOT a member of THIS schedule.
func seedWorkerSchedule(st store.Store) { seedScheduleCreatedBy(st, "user_worker_1") }

func shiftURL() string {
	return "/v1/tenants/" + reqTenant + "/schedules/" + reqSched + "/shift-requests"
}

func changeURL() string {
	return "/v1/tenants/" + reqTenant + "/schedules/" + reqSched + "/change-requests"
}

// ---------------------------------------------------------------------------
// Shift-swap requests: create / list / get
// ---------------------------------------------------------------------------

func TestShiftRequestsCreateAndList(t *testing.T) {
	t.Run("member creates a shift request (PENDING) then lists it", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)

		create := do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{
			"builtScheduleId":   "built_1",
			"shiftToChangeFrom": "2026-06-10T09:00:00Z",
			"shiftToChangeTo":   "2026-06-11T09:00:00Z",
		})
		assertStatus(t, create, http.StatusCreated)
		b := jsonBody(t, create)
		if b["shift_request_status"] != "PENDING" {
			t.Errorf("shift_request_status = %v, want PENDING", b["shift_request_status"])
		}
		// requesting_employee (typo key preserved) must be the actor, server-set.
		if b["reuqesting_employee"] != "user_mgr_1" {
			t.Errorf("reuqesting_employee = %v, want user_mgr_1 (server-set)", b["reuqesting_employee"])
		}
		if _, ok := b["id"].(string); !ok || b["id"] == "" {
			t.Fatal("id should be set")
		}

		list := do(app, "GET", shiftURL(), managerHeaders, nil)
		assertStatus(t, list, http.StatusOK)
		items, _ := jsonBody(t, list)["items"].([]interface{})
		if len(items) != 1 {
			t.Fatalf("items length = %d, want 1", len(items))
		}
	})

	t.Run("requesting_employee is server-set, never trusted from body", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		create := do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{
			"builtScheduleId":     "built_1",
			"reuqesting_employee": "user_someone_else", // attempt to spoof — must be ignored.
		})
		assertStatus(t, create, http.StatusCreated)
		if jsonBody(t, create)["reuqesting_employee"] != "user_mgr_1" {
			t.Error("spoofed reuqesting_employee must be overridden by the actor uid")
		}
	})

	t.Run("rejects create without builtScheduleId", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		w := do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"shiftToChangeFrom": "x"})
		assertStatus(t, w, http.StatusBadRequest)
		if got := jsonBody(t, w)["error"]; got != "invalid_argument" {
			t.Errorf("error = %v, want invalid_argument", got)
		}
	})

	t.Run("get by id", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		w := do(app, "GET", shiftURL()+"/"+id, managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		if jsonBody(t, w)["id"] != id {
			t.Errorf("id mismatch")
		}
	})

	t.Run("get unknown -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		w := do(app, "GET", shiftURL()+"/nope", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		if jsonBody(t, w)["error"] != "shift_request_not_found" {
			t.Errorf("want shift_request_not_found")
		}
	})
}

// ---------------------------------------------------------------------------
// Shift-swap requests: status transitions (table-driven)
// ---------------------------------------------------------------------------

func TestShiftRequestStatusTransitions(t *testing.T) {
	cases := []struct {
		name       string
		status     string
		wantStatus int
		wantBody   string // expected response status value on success
	}{
		{"accept", "ACCEPTED", http.StatusOK, "ACCEPTED"},
		{"reject preserves Flutter typo", "REJECETED", http.StatusOK, "REJECETED"},
		{"correctly-spelled REJECTED is invalid", "REJECTED", http.StatusBadRequest, ""},
		{"PENDING is not a valid manual target", "PENDING", http.StatusBadRequest, ""},
		{"garbage status -> 400", "WAT", http.StatusBadRequest, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			st := store.NewMemoryStore()
			seedManagerSchedule(st)
			app := newApp(st)
			id := jsonBody(t, do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
			w := do(app, "PATCH", shiftURL()+"/"+id, managerHeaders, map[string]interface{}{"status": tc.status})
			assertStatus(t, w, tc.wantStatus)
			if tc.wantBody != "" && jsonBody(t, w)["shift_request_status"] != tc.wantBody {
				t.Errorf("shift_request_status = %v, want %v", jsonBody(t, w)["shift_request_status"], tc.wantBody)
			}
		})
	}

	t.Run("reviewer uid + timestamp recorded on accept", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		w := do(app, "PATCH", shiftURL()+"/"+id, managerHeaders, map[string]interface{}{"status": "ACCEPTED"})
		b := jsonBody(t, w)
		if b["reviewer_uid"] != "user_mgr_1" {
			t.Errorf("reviewer_uid = %v, want user_mgr_1", b["reviewer_uid"])
		}
		if b["reviewed_at"] == nil || b["reviewed_at"] == "" {
			t.Error("reviewed_at should be set")
		}
	})

	t.Run("double review -> 409 already resolved", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		first := do(app, "PATCH", shiftURL()+"/"+id, managerHeaders, map[string]interface{}{"status": "ACCEPTED"})
		assertStatus(t, first, http.StatusOK)
		second := do(app, "PATCH", shiftURL()+"/"+id, managerHeaders, map[string]interface{}{"status": "REJECETED"})
		assertStatus(t, second, http.StatusConflict)
		if jsonBody(t, second)["error"] != "shift_request_already_resolved" {
			t.Errorf("want shift_request_already_resolved")
		}
	})
}

// ---------------------------------------------------------------------------
// Shift-swap requests: delete (author-only, PENDING-only)
// ---------------------------------------------------------------------------

func TestShiftRequestDelete(t *testing.T) {
	t.Run("author deletes own PENDING request", func(t *testing.T) {
		st := store.NewMemoryStore()
		// Employee owns the schedule, so the employee is a member and the author.
		seedWorkerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), employeeHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		w := do(app, "DELETE", shiftURL()+"/"+id, employeeHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		if jsonBody(t, w)["success"] != true {
			t.Errorf("success = %v, want true", jsonBody(t, w)["success"])
		}
		if st.GetShiftRequest(reqTenant, id) != nil {
			t.Error("request should be deleted")
		}
	})

	t.Run("non-author member cannot delete -> 403 not_request_author", func(t *testing.T) {
		st := store.NewMemoryStore()
		// Manager owns the schedule (member). Manager creates the request, so the
		// manager is the AUTHOR; a different member must not delete it. To get a
		// second member who is NOT the author we need another member — but on this
		// base membership is creator-only, so instead assert the inverse: a member
		// who is not the author is blocked. We simulate by making the worker the
		// author and the manager the (creator) member who tries to delete.
		st.PutSchedule(store.Schedule{
			ID: reqSched, TenantID: reqTenant, Name: "R",
			Settings: map[string]interface{}{}, Status: "published", CreatedBy: "user_mgr_1",
		})
		app := newApp(st)
		// Manager (member + author) creates.
		id := jsonBody(t, do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		// Seed a second request authored by someone else, then try to delete it as
		// the manager (a member but NOT the author).
		st.PutShiftRequest(store.ShiftRequest{
			ID: "shiftreq_other", TenantID: reqTenant, ScheduleID: reqSched,
			RequestingEmployee: "user_someone_else", Status: "PENDING", CreatedAt: "2026-06-01T00:00:00Z",
		})
		w := do(app, "DELETE", shiftURL()+"/shiftreq_other", managerHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_request_author" {
			t.Errorf("want not_request_author, got %v", jsonBody(t, w)["error"])
		}
		// The manager's own request still deletes fine.
		assertStatus(t, do(app, "DELETE", shiftURL()+"/"+id, managerHeaders, nil), http.StatusOK)
	})

	t.Run("cannot delete a resolved (non-PENDING) request -> 409", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), employeeHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		// Force-resolve in the store (a manager would do this via PATCH).
		req := st.GetShiftRequest(reqTenant, id)
		req.Status = "ACCEPTED"
		st.PutShiftRequest(*req)
		w := do(app, "DELETE", shiftURL()+"/"+id, employeeHeaders, nil)
		assertStatus(t, w, http.StatusConflict)
		if jsonBody(t, w)["error"] != "shift_request_not_pending" {
			t.Errorf("want shift_request_not_pending")
		}
	})

	t.Run("delete unknown -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		w := do(app, "DELETE", shiftURL()+"/missing", employeeHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})
}

// ---------------------------------------------------------------------------
// IDOR / authorization — the load-bearing security property
// ---------------------------------------------------------------------------

func TestRequestsMembershipACL(t *testing.T) {
	// A caller with valid tenant auth who is NOT a member of the schedule must
	// be denied. This is the core IDOR protection for the requests domain.
	t.Run("non-member cannot list shift requests -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedScheduleCreatedBy(st, "user_someone_else") // manager (user_mgr_1) is NOT a member.
		app := newApp(st)
		w := do(app, "GET", shiftURL(), managerHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_a_schedule_member" {
			t.Errorf("error = %v, want not_a_schedule_member", jsonBody(t, w)["error"])
		}
	})

	t.Run("non-member cannot create a shift request -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedScheduleCreatedBy(st, "user_someone_else")
		app := newApp(st)
		w := do(app, "POST", shiftURL(), managerHeaders, map[string]interface{}{"builtScheduleId": "b"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_a_schedule_member" {
			t.Errorf("want not_a_schedule_member")
		}
	})

	t.Run("non-member manager cannot review another schedule's request -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedScheduleCreatedBy(st, "user_someone_else")
		// A request exists on this schedule (authored by the real member).
		st.PutShiftRequest(store.ShiftRequest{
			ID: "shiftreq_x", TenantID: reqTenant, ScheduleID: reqSched,
			RequestingEmployee: "user_someone_else", Status: "PENDING", CreatedAt: "2026-06-01T00:00:00Z",
		})
		app := newApp(st)
		// The manager passes the router managerOnly gate but is NOT a member —
		// the handler's membership check must still block them (403), NOT mutate.
		w := do(app, "PATCH", shiftURL()+"/shiftreq_x", managerHeaders, map[string]interface{}{"status": "ACCEPTED"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_a_schedule_member" {
			t.Errorf("want not_a_schedule_member, got %v", jsonBody(t, w)["error"])
		}
		// And the request must be untouched.
		if st.GetShiftRequest(reqTenant, "shiftreq_x").Status != "PENDING" {
			t.Error("non-member review must not have mutated the request")
		}
	})

	t.Run("missing schedule -> 404 before ACL", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "GET", shiftURL(), managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		if jsonBody(t, w)["error"] != "schedule_not_found" {
			t.Errorf("want schedule_not_found")
		}
	})

	t.Run("cross-tenant request id is not reachable", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st) // tenant_security_demo
		// A request with the same id under a DIFFERENT tenant must not leak.
		st.PutShiftRequest(store.ShiftRequest{
			ID: "shiftreq_cross", TenantID: "tenant_other", ScheduleID: reqSched,
			RequestingEmployee: "user_mgr_1", Status: "PENDING",
		})
		app := newApp(st)
		w := do(app, "GET", shiftURL()+"/shiftreq_cross", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})
}

// ---------------------------------------------------------------------------
// Role enforcement (router managerOnly on status transitions)
// ---------------------------------------------------------------------------

func TestRequestsRoleEnforcement(t *testing.T) {
	t.Run("employee member cannot review a shift request (manager-only) -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		// Employee owns the schedule (member) and authors the request.
		seedWorkerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", shiftURL(), employeeHeaders, map[string]interface{}{"builtScheduleId": "b"}))["id"].(string)
		// Employee tries to approve their own request — managerOnly fires first.
		w := do(app, "PATCH", shiftURL()+"/"+id, employeeHeaders, map[string]interface{}{"status": "ACCEPTED"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "manager_approval_required" {
			t.Errorf("error = %v, want manager_approval_required", jsonBody(t, w)["error"])
		}
	})

	t.Run("employee member cannot review a change request (manager-only) -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", changeURL(), employeeHeaders, map[string]interface{}{"reason": "swap please"}))["id"].(string)
		w := do(app, "PATCH", changeURL()+"/"+id, employeeHeaders, map[string]interface{}{"status": "accepted"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "manager_approval_required" {
			t.Errorf("want manager_approval_required")
		}
	})
}

// ---------------------------------------------------------------------------
// Schedule-change requests: create / list / get / status (table-driven)
// ---------------------------------------------------------------------------

func TestChangeRequestsCreateAndList(t *testing.T) {
	t.Run("member creates a change request (sent) then lists it", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		create := do(app, "POST", changeURL(), employeeHeaders, map[string]interface{}{
			"reason":   "I need Tuesday off",
			"dateTime": "2026-06-15T00:00:00Z",
		})
		assertStatus(t, create, http.StatusCreated)
		b := jsonBody(t, create)
		if b["status"] != "sent" {
			t.Errorf("status = %v, want sent", b["status"])
		}
		// Capitalised FlutterFlow keys preserved verbatim.
		if b["Reason"] != "I need Tuesday off" {
			t.Errorf("Reason = %v, want the reason text", b["Reason"])
		}
		if b["userId"] != "user_worker_1" {
			t.Errorf("userId = %v, want user_worker_1 (server-set)", b["userId"])
		}

		list := do(app, "GET", changeURL(), employeeHeaders, nil)
		assertStatus(t, list, http.StatusOK)
		items, _ := jsonBody(t, list)["items"].([]interface{})
		if len(items) != 1 {
			t.Fatalf("items length = %d, want 1", len(items))
		}
	})

	t.Run("rejects create without reason", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		w := do(app, "POST", changeURL(), employeeHeaders, map[string]interface{}{"dateTime": "x"})
		assertStatus(t, w, http.StatusBadRequest)
		if jsonBody(t, w)["error"] != "invalid_argument" {
			t.Errorf("want invalid_argument")
		}
	})

	t.Run("creator cannot self-approve via create status", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedWorkerSchedule(st)
		app := newApp(st)
		w := do(app, "POST", changeURL(), employeeHeaders, map[string]interface{}{
			"reason": "sneaky", "status": "accepted",
		})
		assertStatus(t, w, http.StatusBadRequest)
		if jsonBody(t, w)["error"] != "invalid_status" {
			t.Errorf("want invalid_status")
		}
	})
}

func TestChangeRequestStatusTransitions(t *testing.T) {
	cases := []struct {
		name       string
		status     string
		wantStatus int
		want       string
	}{
		{"accept", "accepted", http.StatusOK, "accepted"},
		{"decline", "declined", http.StatusOK, "declined"},
		{"sent is not a valid manual target", "sent", http.StatusBadRequest, ""},
		{"garbage -> 400", "approved", http.StatusBadRequest, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			st := store.NewMemoryStore()
			seedManagerSchedule(st) // manager is the member + reviewer
			app := newApp(st)
			id := jsonBody(t, do(app, "POST", changeURL(), managerHeaders, map[string]interface{}{"reason": "r"}))["id"].(string)
			w := do(app, "PATCH", changeURL()+"/"+id, managerHeaders, map[string]interface{}{"status": tc.status})
			assertStatus(t, w, tc.wantStatus)
			if tc.want != "" {
				b := jsonBody(t, w)
				if b["status"] != tc.want {
					t.Errorf("status = %v, want %v", b["status"], tc.want)
				}
				if b["reviewer_uid"] != "user_mgr_1" {
					t.Errorf("reviewer_uid = %v, want user_mgr_1", b["reviewer_uid"])
				}
				if b["resolved_at"] == nil || b["resolved_at"] == "" {
					t.Error("resolved_at should be set")
				}
			}
		})
	}

	t.Run("double review -> 409 already resolved", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		id := jsonBody(t, do(app, "POST", changeURL(), managerHeaders, map[string]interface{}{"reason": "r"}))["id"].(string)
		assertStatus(t, do(app, "PATCH", changeURL()+"/"+id, managerHeaders, map[string]interface{}{"status": "accepted"}), http.StatusOK)
		second := do(app, "PATCH", changeURL()+"/"+id, managerHeaders, map[string]interface{}{"status": "declined"})
		assertStatus(t, second, http.StatusConflict)
		if jsonBody(t, second)["error"] != "change_request_already_resolved" {
			t.Errorf("want change_request_already_resolved")
		}
	})

	t.Run("get unknown change request -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedManagerSchedule(st)
		app := newApp(st)
		w := do(app, "GET", changeURL()+"/nope", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		if jsonBody(t, w)["error"] != "change_request_not_found" {
			t.Errorf("want change_request_not_found")
		}
	})

	t.Run("non-member cannot list change requests -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedScheduleCreatedBy(st, "user_someone_else")
		app := newApp(st)
		w := do(app, "GET", changeURL(), managerHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_a_schedule_member" {
			t.Errorf("want not_a_schedule_member")
		}
	})
}
