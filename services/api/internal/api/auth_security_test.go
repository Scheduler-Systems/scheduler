package api_test

// auth_security_test.go contains the regression tests for issue #19:
// "Auth contract: derive actor role from verified Firebase token
// (X-User-Role is client-trusted)".
//
// Before the fix, the API read the actor's role (and identity) from
// client-supplied headers (X-User-Role / X-User-Id / X-Tenant-Id), so any
// client could self-claim manager/owner — a privilege-escalation vulnerability.
//
// These tests prove:
//   (a) a request with a forged X-User-Role: owner header does NOT get owner
//       (or manager) privileges, and
//   (b) the role is read from the verified token claims, not from the header.

import (
	"net/http"
	"testing"

	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// managerOnlyCreate is a manager-only route used as the privilege probe.
const managerOnlyCreate = "/v1/tenants/tenant_security_demo/schedules"

// (a) Forged X-User-Role: owner must NOT grant privileges.
//
// The caller presents a legitimate EMPLOYEE token but tacks on the headers the
// old code trusted (X-User-Role: owner, X-User-Id: someone_else). The request
// must still be treated as an employee and rejected from the manager-only
// create route with 403 manager_approval_required.
func TestForgedRoleHeaderDoesNotEscalate(t *testing.T) {
	st := store.NewMemoryStore()
	app := newApp(st)

	// Employee token + forged elevation headers.
	h := mergeHeaders(employeeHeaders, map[string]string{
		"X-User-Role": "owner",        // forged
		"X-User-Id":   "user_owner_1", // forged
		"X-Tenant-Id": "tenant_other", // forged
	})

	w := do(app, "POST", managerOnlyCreate, h, map[string]interface{}{
		"id":       "schedule_escalation_attempt",
		"name":     "Escalation Attempt",
		"settings": map[string]interface{}{},
	})

	assertStatus(t, w, http.StatusForbidden)
	b := jsonBody(t, w)
	if b["error"] != "manager_approval_required" {
		t.Fatalf("forged owner header escalated: error = %v, want manager_approval_required", b["error"])
	}

	// And nothing was written under any tenant.
	if got := len(st.ListSchedules("tenant_security_demo")); got != 0 {
		t.Errorf("schedule was created despite 403: %d schedules in tenant_security_demo", got)
	}
	if got := len(st.ListSchedules("tenant_other")); got != 0 {
		t.Errorf("schedule leaked into forged tenant: %d schedules in tenant_other", got)
	}
}

// Forged role header must not escalate a manager to owner-only behavior either,
// nor demote — i.e. role tracks the token regardless of the header value.
func TestRoleTracksTokenNotHeader(t *testing.T) {
	st := store.NewMemoryStore()
	app := newApp(st)

	// Manager token, but header tries to DOWNGRADE to employee. The manager
	// token must still be allowed to create (header is ignored entirely).
	h := mergeHeaders(managerHeaders, map[string]string{"X-User-Role": "employee"})
	w := do(app, "POST", managerOnlyCreate, h, map[string]interface{}{
		"name":     "Manager Created Despite Downgrade Header",
		"settings": map[string]interface{}{},
	})
	assertStatus(t, w, http.StatusCreated)
}

// (b) Role and identity are read from the verified token claims.
//
// The created schedule's createdBy must equal the token's uid, not any
// X-User-Id header value.
func TestIdentityComesFromTokenNotHeader(t *testing.T) {
	st := store.NewMemoryStore()
	app := newApp(st)

	// Manager token (uid user_mgr_1) with a forged X-User-Id header.
	h := mergeHeaders(managerHeaders, map[string]string{"X-User-Id": "attacker_uid"})
	w := do(app, "POST", managerOnlyCreate, h, map[string]interface{}{
		"id":       "s_identity",
		"name":     "Identity Check",
		"settings": map[string]interface{}{},
	})
	assertStatus(t, w, http.StatusCreated)
	b := jsonBody(t, w)
	if b["createdBy"] != "user_mgr_1" {
		t.Fatalf("createdBy = %v, want user_mgr_1 (token uid, not header)", b["createdBy"])
	}
}

// Employee token on a manager-only route is denied even with no forgery —
// baseline confirming the boundary is real and driven by the token role.
func TestEmployeeTokenDeniedOnManagerRoute(t *testing.T) {
	st := store.NewMemoryStore()
	app := newApp(st)
	w := do(app, "POST", managerOnlyCreate, employeeHeaders, map[string]interface{}{
		"name": "Should Be Denied", "settings": map[string]interface{}{},
	})
	assertStatus(t, w, http.StatusForbidden)
}

// A token with an unknown/garbage role claim must fail closed to employee
// (least privilege), so it cannot reach a manager-only route.
func TestUnknownRoleClaimFailsClosed(t *testing.T) {
	st := store.NewMemoryStore()
	app := newApp(st)
	h := map[string]string{
		"Authorization":    "Bearer " + mintToken("user_x", "tenant_security_demo", auth.Role("superadmin")),
		"X-Correlation-Id": "corr_test_1",
	}
	w := do(app, "POST", managerOnlyCreate, h, map[string]interface{}{
		"name": "Garbage Role", "settings": map[string]interface{}{},
	})
	assertStatus(t, w, http.StatusForbidden)
}
