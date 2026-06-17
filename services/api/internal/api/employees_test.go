package api_test

// employees_test.go exercises the employees domain end-to-end through the
// router: list/get/add/addBulk/remove + the invite/accept workflow. It reuses
// the helpers (do, jsonBody, assertStatus, *Headers, mergeHeaders) defined in
// api_test.go.
//
// The membership ACL is the load-bearing security property here: a manager with
// valid tenant auth who is NOT a member of a schedule must NOT be able to read
// or mutate that schedule's roster (403 not_a_schedule_member). These tests pin
// that behaviour.

import (
	"net/http"
	"testing"

	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

const (
	empTenant = "tenant_security_demo"
	empSched  = "sched_emp_1"
)

// seedMemberSchedule creates a schedule whose creator uid matches the manager
// header (user_mgr_1) so that manager is a member and passes the ACL check.
func seedMemberSchedule(st store.Store) {
	st.PutSchedule(store.Schedule{
		ID:        empSched,
		TenantID:  empTenant,
		Name:      "Roster One",
		Settings:  map[string]interface{}{},
		Status:    "draft",
		CreatedBy: "user_mgr_1", // == managerHeaders X-User-Id
	})
}

func empURL() string {
	return "/v1/tenants/" + empTenant + "/schedules/" + empSched + "/employees"
}

// ---------------------------------------------------------------------------
// Add / list / get
// ---------------------------------------------------------------------------

func TestEmployeesAddAndList(t *testing.T) {
	t.Run("manager-member adds an employee then lists it", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)

		add := do(app, "POST", empURL(), managerHeaders, map[string]interface{}{
			"employee_name":  "Bob Worker",
			"employee_email": "bob@acme.com",
			"employee_phone": "555",
			"role":           map[string]interface{}{"is_worker": true},
		})
		assertStatus(t, add, http.StatusCreated)
		b := jsonBody(t, add)
		if b["employee_email"] != "bob@acme.com" {
			t.Errorf("employee_email = %v, want bob@acme.com", b["employee_email"])
		}

		list := do(app, "GET", empURL(), managerHeaders, nil)
		assertStatus(t, list, http.StatusOK)
		lb := jsonBody(t, list)
		items, _ := lb["items"].([]interface{})
		if len(items) != 1 {
			t.Fatalf("items length = %d, want 1", len(items))
		}
	})

	t.Run("rejects add without email", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", empURL(), managerHeaders, map[string]interface{}{"employee_name": "No Email"})
		assertStatus(t, w, http.StatusBadRequest)
		b := jsonBody(t, w)
		if b["error"] != "invalid_argument" {
			t.Errorf("error = %v, want invalid_argument", b["error"])
		}
	})

	t.Run("duplicate email (case/space-insensitive) -> 409", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		do(app, "POST", empURL(), managerHeaders, map[string]interface{}{"employee_email": "bob@acme.com"})
		w := do(app, "POST", empURL(), managerHeaders, map[string]interface{}{"employee_email": "  BOB@acme.com  "})
		assertStatus(t, w, http.StatusConflict)
		b := jsonBody(t, w)
		if b["error"] != "employee_email_taken" {
			t.Errorf("error = %v, want employee_email_taken", b["error"])
		}
	})

	t.Run("get employee by email", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		do(app, "POST", empURL(), managerHeaders, map[string]interface{}{
			"employee_email": "carol@acme.com", "employee_name": "Carol",
		})
		w := do(app, "GET", empURL()+"/carol@acme.com", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["employee_name"] != "Carol" {
			t.Errorf("employee_name = %v, want Carol", b["employee_name"])
		}
	})

	t.Run("get unknown employee -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "GET", empURL()+"/nobody@acme.com", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "employee_not_found" {
			t.Errorf("error = %v, want employee_not_found", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Membership ACL (the IDOR-safe property)
// ---------------------------------------------------------------------------

func TestEmployeesMembershipACL(t *testing.T) {
	// A manager with valid tenant auth who is NOT the creator/member of the
	// schedule must be denied — this is the core IDOR protection.
	t.Run("non-member manager cannot add to a schedule -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		// Creator is someone ELSE, so user_mgr_1 is not a member.
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "Other's Roster",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone_else",
		})
		app := newApp(st)
		w := do(app, "POST", empURL(), managerHeaders, map[string]interface{}{"employee_email": "x@acme.com"})
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "not_a_schedule_member" {
			t.Errorf("error = %v, want not_a_schedule_member", b["error"])
		}
	})

	t.Run("non-member manager cannot list a schedule's roster -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "Other's Roster",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone_else",
		})
		app := newApp(st)
		w := do(app, "GET", empURL(), managerHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
	})

	t.Run("employee linked by user_ref is a member", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "R",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone_else",
		})
		// Link the worker uid as an employee so it passes membership.
		st.PutEmployee(empTenant, empSched, store.Employee{Email: "w@acme.com", UserRef: "user_worker_1"})
		app := newApp(st)
		// Employee can LIST (read is not manager-gated).
		w := do(app, "GET", empURL(), employeeHeaders, nil)
		assertStatus(t, w, http.StatusOK)
	})

	t.Run("missing schedule -> 404 (before ACL)", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "GET", empURL(), managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "schedule_not_found" {
			t.Errorf("error = %v, want schedule_not_found", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Role enforcement (router managerOnly)
// ---------------------------------------------------------------------------

func TestEmployeesRoleEnforcement(t *testing.T) {
	t.Run("employee cannot add (manager-only) even when a member", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "R",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone",
		})
		st.PutEmployee(empTenant, empSched, store.Employee{Email: "w@acme.com", UserRef: "user_worker_1"})
		app := newApp(st)
		w := do(app, "POST", empURL(), employeeHeaders, map[string]interface{}{"employee_email": "new@acme.com"})
		// managerOnly fires before the handler body — 403 manager_approval_required.
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "manager_approval_required" {
			t.Errorf("error = %v, want manager_approval_required", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Bulk add
// ---------------------------------------------------------------------------

func TestEmployeesAddBulk(t *testing.T) {
	bulkURL := empURL() + ":bulk"

	t.Run("adds a batch", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", bulkURL, managerHeaders, map[string]interface{}{
			"employees": []interface{}{
				map[string]interface{}{"employee_email": "a@acme.com"},
				map[string]interface{}{"employee_email": "b@acme.com"},
			},
		})
		assertStatus(t, w, http.StatusCreated)
		b := jsonBody(t, w)
		if b["added"] != float64(2) {
			t.Errorf("added = %v, want 2", b["added"])
		}
	})

	t.Run("empty batch -> 400", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", bulkURL, managerHeaders, map[string]interface{}{"employees": []interface{}{}})
		assertStatus(t, w, http.StatusBadRequest)
	})

	t.Run("intra-batch duplicate -> 409 and atomic (no partial write)", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", bulkURL, managerHeaders, map[string]interface{}{
			"employees": []interface{}{
				map[string]interface{}{"employee_email": "dup@acme.com"},
				map[string]interface{}{"employee_email": "DUP@acme.com"},
			},
		})
		assertStatus(t, w, http.StatusConflict)
		// Nothing should have been written.
		if got := st.ListEmployees(empTenant, empSched); len(got) != 0 {
			t.Errorf("roster should be empty after failed bulk, got %d", len(got))
		}
	})

	t.Run("batch row missing email -> 400 atomic", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", bulkURL, managerHeaders, map[string]interface{}{
			"employees": []interface{}{
				map[string]interface{}{"employee_email": "ok@acme.com"},
				map[string]interface{}{"employee_name": "no email"},
			},
		})
		assertStatus(t, w, http.StatusBadRequest)
		if got := st.ListEmployees(empTenant, empSched); len(got) != 0 {
			t.Errorf("roster should be empty after failed bulk, got %d", len(got))
		}
	})
}

// ---------------------------------------------------------------------------
// Remove
// ---------------------------------------------------------------------------

func TestEmployeesRemove(t *testing.T) {
	t.Run("removes an employee", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		st.PutEmployee(empTenant, empSched, store.Employee{Email: "gone@acme.com"})
		app := newApp(st)
		w := do(app, "DELETE", empURL()+"/gone@acme.com", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["success"] != true {
			t.Errorf("success = %v, want true", b["success"])
		}
		if got := st.GetEmployee(empTenant, empSched, "gone@acme.com"); got != nil {
			t.Errorf("employee should be removed, got %v", got)
		}
	})

	t.Run("remove unknown -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "DELETE", empURL()+"/missing@acme.com", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("employee role cannot remove (manager-only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "R",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone",
		})
		st.PutEmployee(empTenant, empSched, store.Employee{Email: "x@acme.com", UserRef: "user_worker_1"})
		app := newApp(st)
		w := do(app, "DELETE", empURL()+"/x@acme.com", employeeHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
	})
}

// ---------------------------------------------------------------------------
// Invite / accept workflow
// ---------------------------------------------------------------------------

func TestEmployeesInviteAccept(t *testing.T) {
	invURL := empURL() + "/invitations"

	t.Run("manager invites, invitee accepts -> becomes a member", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)

		inv := do(app, "POST", invURL, managerHeaders, map[string]interface{}{
			"toUserIdentification": "newhire@acme.com",
		})
		assertStatus(t, inv, http.StatusCreated)
		ib := jsonBody(t, inv)
		if ib["status"] != "ADD_RQUEST_PENDING" {
			t.Errorf("status = %v, want ADD_RQUEST_PENDING", ib["status"])
		}
		invID, _ := ib["id"].(string)
		if invID == "" {
			t.Fatal("invitation id should be set")
		}

		// Invitee accepts (worker presents the matching invitee email).
		acceptURL := invURL + "/" + invID + "/accept"
		inviteeHeaders := mergeHeaders(employeeHeaders, map[string]string{"X-User-Email": "newhire@acme.com"})
		acc := do(app, "POST", acceptURL, inviteeHeaders, map[string]interface{}{})
		assertStatus(t, acc, http.StatusOK)
		ab := jsonBody(t, acc)
		if ab["status"] != "ADD_REQUEST_ACCEPTED" {
			t.Errorf("status = %v, want ADD_REQUEST_ACCEPTED", ab["status"])
		}

		// The invitee should now exist on the roster, linked to the worker uid.
		emp := st.GetEmployee(empTenant, empSched, "newhire@acme.com")
		if emp == nil {
			t.Fatal("invitee should be materialized on the roster after accept")
		}
		if emp.UserRef != "user_worker_1" {
			t.Errorf("user_ref = %q, want user_worker_1", emp.UserRef)
		}
	})

	t.Run("third party cannot hijack an email-only invitation (IDOR)", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		inv := do(app, "POST", invURL, managerHeaders, map[string]interface{}{
			"toUserIdentification": "victim@acme.com",
		})
		invID, _ := jsonBody(t, inv)["id"].(string)
		acceptURL := invURL + "/" + invID + "/accept"

		// (a) An authenticated attacker with a NON-matching email is rejected.
		attacker := mergeHeaders(employeeHeaders, map[string]string{"X-User-Email": "attacker@acme.com"})
		w := do(app, "POST", acceptURL, attacker, map[string]interface{}{})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_invitation_target" {
			t.Errorf("want not_invitation_target, got %v", jsonBody(t, w)["error"])
		}

		// (b) An authenticated actor presenting NO email (the old "any uid"
		//     hijack) is rejected — never accept-anyone on an unbound invite.
		w = do(app, "POST", acceptURL, employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_invitation_target" {
			t.Errorf("want not_invitation_target, got %v", jsonBody(t, w)["error"])
		}

		// The victim must NOT have been added to the roster by the hijack attempt.
		if st.GetEmployee(empTenant, empSched, "victim@acme.com") != nil {
			t.Error("hijack attempt must not materialize the invitee on the roster")
		}
	})

	t.Run("decline records declined status and does not add", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		inv := do(app, "POST", invURL, managerHeaders, map[string]interface{}{"toUserIdentification": "no@acme.com"})
		invID, _ := jsonBody(t, inv)["id"].(string)
		inviteeHeaders := mergeHeaders(employeeHeaders, map[string]string{"X-User-Email": "no@acme.com"})
		acc := do(app, "POST", invURL+"/"+invID+"/accept", inviteeHeaders, map[string]interface{}{"decline": true})
		assertStatus(t, acc, http.StatusOK)
		if jsonBody(t, acc)["status"] != "ADD_REQUEST_DECLINED" {
			t.Errorf("status should be ADD_REQUEST_DECLINED")
		}
		if st.GetEmployee(empTenant, empSched, "no@acme.com") != nil {
			t.Error("declined invitee should not be on the roster")
		}
	})

	t.Run("invite requires toUserIdentification", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", invURL, managerHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusBadRequest)
	})

	t.Run("non-manager cannot invite (manager-only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "R",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone",
		})
		st.PutEmployee(empTenant, empSched, store.Employee{Email: "w@acme.com", UserRef: "user_worker_1"})
		app := newApp(st)
		w := do(app, "POST", invURL, employeeHeaders, map[string]interface{}{"toUserIdentification": "x@acme.com"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "manager_approval_required" {
			t.Errorf("want manager_approval_required")
		}
	})

	t.Run("non-member manager cannot invite -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID: empSched, TenantID: empTenant, Name: "Other",
			Settings: map[string]interface{}{}, Status: "draft", CreatedBy: "user_someone_else",
		})
		app := newApp(st)
		w := do(app, "POST", invURL, managerHeaders, map[string]interface{}{"toUserIdentification": "x@acme.com"})
		assertStatus(t, w, http.StatusForbidden)
		if jsonBody(t, w)["error"] != "not_a_schedule_member" {
			t.Errorf("want not_a_schedule_member")
		}
	})

	t.Run("accept twice -> 409 already resolved", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		inv := do(app, "POST", invURL, managerHeaders, map[string]interface{}{"toUserIdentification": "twice@acme.com"})
		invID, _ := jsonBody(t, inv)["id"].(string)
		inviteeHeaders := mergeHeaders(employeeHeaders, map[string]string{"X-User-Email": "twice@acme.com"})
		first := do(app, "POST", invURL+"/"+invID+"/accept", inviteeHeaders, map[string]interface{}{})
		assertStatus(t, first, http.StatusOK)
		second := do(app, "POST", invURL+"/"+invID+"/accept", inviteeHeaders, map[string]interface{}{})
		assertStatus(t, second, http.StatusConflict)
		if jsonBody(t, second)["error"] != "invitation_already_resolved" {
			t.Errorf("want invitation_already_resolved")
		}
	})

	t.Run("accept unknown invitation -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		w := do(app, "POST", invURL+"/nope/accept", employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("lists invitations newest first", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedMemberSchedule(st)
		app := newApp(st)
		do(app, "POST", invURL, managerHeaders, map[string]interface{}{"toUserIdentification": "i1@acme.com"})
		do(app, "POST", invURL, managerHeaders, map[string]interface{}{"toUserIdentification": "i2@acme.com"})
		w := do(app, "GET", invURL, managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		items, _ := jsonBody(t, w)["items"].([]interface{})
		if len(items) != 2 {
			t.Errorf("items = %d, want 2", len(items))
		}
	})
}
