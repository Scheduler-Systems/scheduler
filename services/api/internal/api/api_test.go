package api_test

// api_test.go is a full port of test/app.test.mjs to Go's testing package.
//
// Each JS test case maps 1:1 to a Go sub-test under the corresponding group
// name.  The test helper `do` drives the handler directly via
// httptest.NewRecorder so no real network is needed.

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"sort"
	"strings"
	"sync"
	"testing"

	"github.com/Scheduler-Systems/scheduler-api/internal/api"
	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// ---------------------------------------------------------------------------
// Test verifier
//
// Production Authenticate derives identity + role ONLY from the verified token
// (issue #19). For tests we use a deterministic fake verifier: the bearer token
// is a base64-encoded JSON auth.Token, so the test controls exactly what a
// "verified" token would have claimed. This proves that authority comes from
// the token, not from request headers — forged X-User-Role/X-User-Id/X-Tenant-Id
// headers are ignored because the fixtures put no authority in headers and the
// verifier never reads them.
// ---------------------------------------------------------------------------

type fakeVerifier struct{}

func (fakeVerifier) Verify(_ context.Context, raw string) (*auth.Token, error) {
	if raw == "" || raw == "test" {
		return nil, auth.ErrInvalidToken
	}
	data, err := base64.RawURLEncoding.DecodeString(raw)
	if err != nil {
		return nil, auth.ErrInvalidToken
	}
	var tok auth.Token
	if err := json.Unmarshal(data, &tok); err != nil {
		return nil, auth.ErrInvalidToken
	}
	if tok.UserID == "" || tok.TenantID == "" {
		return nil, auth.ErrMissingClaim
	}
	// Re-normalize the role exactly as the real verifier would, so a token
	// claiming an unknown role falls back to employee.
	tok.Role = auth.NormalizeRole(string(tok.Role))
	return &tok, nil
}

// mintToken encodes a verified-token claim set into the opaque bearer string
// the fakeVerifier understands.
func mintToken(userID, tenantID string, role auth.Role) string {
	b, _ := json.Marshal(auth.Token{UserID: userID, TenantID: tenantID, Role: role})
	return base64.RawURLEncoding.EncodeToString(b)
}

// bearer builds the request headers for a given verified actor. Note there is
// NO X-User-Role / X-User-Id / X-Tenant-Id header — all authority lives in the
// token.
func bearer(userID, tenantID string, role auth.Role) map[string]string {
	return map[string]string{
		"Authorization":    "Bearer " + mintToken(userID, tenantID, role),
		"X-Correlation-Id": "corr_test_1",
		"Content-Type":     "application/json",
	}
}

// ---------------------------------------------------------------------------
// Test fixtures
// ---------------------------------------------------------------------------

var managerHeaders = bearer("user_mgr_1", "tenant_security_demo", auth.RoleManager)
var employeeHeaders = bearer("user_worker_1", "tenant_security_demo", auth.RoleEmployee)
var ownerHeaders = bearer("user_owner_1", "tenant_security_demo", auth.RoleOwner)

// withTenant returns a copy of the given fixture headers re-minted for a
// different tenant, preserving the same user id and role. Used by tenant-scoped
// tests that previously overrode the X-Tenant-Id header.
func withTenant(src map[string]string, userID, tenant string, role auth.Role) map[string]string {
	out := mergeHeaders(src, map[string]string{
		"Authorization": "Bearer " + mintToken(userID, tenant, role),
	})
	return out
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// newApp returns a fresh handler backed by a new memory store and a generous
// rate limit (10 000 req/min) so tests never accidentally hit the limiter,
// unless they construct their own limiter.
func newApp(st store.Store) http.Handler {
	rl := api.NewRateLimiter(10000)
	return api.NewHandler(st, rl, fakeVerifier{})
}

// newDefaultApp creates a handler with an empty in-memory store.
func newDefaultApp() http.Handler {
	return newApp(store.NewMemoryStore())
}

// do sends a synthetic HTTP request to handler and returns the recorder.
func do(handler http.Handler, method, path string, headers map[string]string, body interface{}) *httptest.ResponseRecorder {
	var buf bytes.Buffer
	if body != nil {
		_ = json.NewEncoder(&buf).Encode(body)
	}
	req := httptest.NewRequest(method, path, &buf)
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)
	return w
}

// jsonBody decodes the recorder's response body into a map.
func jsonBody(t *testing.T, w *httptest.ResponseRecorder) map[string]interface{} {
	t.Helper()
	var m map[string]interface{}
	if err := json.NewDecoder(w.Body).Decode(&m); err != nil {
		t.Fatalf("failed to decode response JSON: %v\nbody: %s", err, w.Body.String())
	}
	return m
}

// assertStatus is a convenience assertion.
func assertStatus(t *testing.T, w *httptest.ResponseRecorder, want int) {
	t.Helper()
	if w.Code != want {
		t.Errorf("status = %d, want %d (body: %s)", w.Code, want, w.Body.String())
	}
}

// mergeHeaders returns a shallow copy of src with overrides applied.
func mergeHeaders(src, overrides map[string]string) map[string]string {
	out := make(map[string]string, len(src)+len(overrides))
	for k, v := range src {
		out[k] = v
	}
	for k, v := range overrides {
		out[k] = v
	}
	return out
}

// deleteKey returns a copy of src without key k.
func deleteKey(src map[string]string, k string) map[string]string {
	out := make(map[string]string, len(src))
	for key, v := range src {
		if key != k {
			out[key] = v
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// Auth tests
// ---------------------------------------------------------------------------

func TestAuth(t *testing.T) {
	t.Run("requires bearer auth", func(t *testing.T) {
		app := newDefaultApp()
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules", nil, nil)
		assertStatus(t, w, http.StatusUnauthorized)
	})

	t.Run("rejects an unverifiable bearer token", func(t *testing.T) {
		app := newDefaultApp()
		// A bearer token that is not a valid verified token is rejected; the
		// caller cannot fall back to header-supplied identity/role.
		h := map[string]string{
			"Authorization":    "Bearer not-a-real-token",
			"X-Correlation-Id": "corr_test_1",
		}
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules", h, nil)
		assertStatus(t, w, http.StatusUnauthorized)
		b := jsonBody(t, w)
		if b["error"] != "invalid_token" {
			t.Errorf("error = %v, want invalid_token", b["error"])
		}
	})

	t.Run("rejects cross-tenant requests", func(t *testing.T) {
		app := newDefaultApp()
		// Token tenant is tenant_security_demo but URL uses tenant_other. The
		// tenant is taken from the verified token, so this is a mismatch.
		w := do(app, "GET", "/v1/tenants/tenant_other/schedules", managerHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "tenant_mismatch" {
			t.Errorf("error = %v, want tenant_mismatch", b["error"])
		}
	})

	t.Run("rejects a token missing its uid claim", func(t *testing.T) {
		app := newDefaultApp()
		// Identity comes from the token; a token with no uid claim is invalid.
		h := map[string]string{
			"Authorization":    "Bearer " + mintToken("", "tenant_security_demo", auth.RoleManager),
			"X-Correlation-Id": "corr_test_1",
		}
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules", h, nil)
		assertStatus(t, w, http.StatusUnauthorized)
		b := jsonBody(t, w)
		if b["error"] != "invalid_token" {
			t.Errorf("error = %v, want invalid_token", b["error"])
		}
	})

	t.Run("rejects request with missing correlation id", func(t *testing.T) {
		app := newDefaultApp()
		h := deleteKey(managerHeaders, "X-Correlation-Id")
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules", h, nil)
		assertStatus(t, w, http.StatusBadRequest)
		b := jsonBody(t, w)
		if b["error"] != "missing_actor_context" {
			t.Errorf("error = %v, want missing_actor_context", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// CRUD schedule tests
// ---------------------------------------------------------------------------

func TestScheduleCRUD(t *testing.T) {
	t.Run("creates and reads a schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		create := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{
				"id":       "schedule_security_weekly",
				"name":     "Security Weekly Roster",
				"status":   "draft",
				"settings": map[string]interface{}{"timeZone": "Asia/Jerusalem", "enabledShifts": []interface{}{}},
			})
		assertStatus(t, create, http.StatusCreated)

		read := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules/schedule_security_weekly",
			managerHeaders, nil)
		assertStatus(t, read, http.StatusOK)
		b := jsonBody(t, read)
		if b["tenantId"] != "tenant_security_demo" {
			t.Errorf("tenantId = %v", b["tenantId"])
		}
		if b["name"] != "Security Weekly Roster" {
			t.Errorf("name = %v", b["name"])
		}
		if b["createdBy"] != "user_mgr_1" {
			t.Errorf("createdBy = %v", b["createdBy"])
		}
	})

	t.Run("creates schedule with auto-generated id", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "Auto ID Schedule", "settings": map[string]interface{}{}})
		assertStatus(t, w, http.StatusCreated)
		b := jsonBody(t, w)
		id, _ := b["id"].(string)
		if !strings.HasPrefix(id, "schedule_") {
			t.Errorf("auto-generated id should start with 'schedule_', got %q", id)
		}
		if b["status"] != "draft" {
			t.Errorf("default status = %v, want draft", b["status"])
		}
	})

	t.Run("lists schedules for a tenant", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		do(app, "POST", "/v1/tenants/tenant_security_demo/schedules", managerHeaders,
			map[string]interface{}{"id": "s1", "name": "Alpha", "settings": map[string]interface{}{}})
		do(app, "POST", "/v1/tenants/tenant_security_demo/schedules", managerHeaders,
			map[string]interface{}{"id": "s2", "name": "Beta", "settings": map[string]interface{}{}})

		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		items, _ := b["items"].([]interface{})
		if len(items) != 2 {
			t.Fatalf("want 2 items, got %d", len(items))
		}
		got := []string{
			items[0].(map[string]interface{})["name"].(string),
			items[1].(map[string]interface{})["name"].(string),
		}
		sort.Strings(got)
		if got[0] != "Alpha" || got[1] != "Beta" {
			t.Errorf("want [Alpha Beta], got %v", got)
		}
	})

	t.Run("lists schedules is tenant-scoped", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "t1", Name: "A", Settings: map[string]interface{}{}, Status: "draft"})
		st.PutSchedule(store.Schedule{ID: "s2", TenantID: "t2", Name: "B", Settings: map[string]interface{}{}, Status: "draft"})

		app := newApp(st)
		h := withTenant(managerHeaders, "user_mgr_1", "t1", auth.RoleManager)
		w := do(app, "GET", "/v1/tenants/t1/schedules", h, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		items, _ := b["items"].([]interface{})
		if len(items) != 1 {
			t.Errorf("items length = %d, want 1", len(items))
		}
		first, _ := items[0].(map[string]interface{})
		if first["name"] != "A" {
			t.Errorf("name = %v, want A", first["name"])
		}
	})

	t.Run("returns 404 for non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/schedules/nonexistent", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "schedule_not_found" {
			t.Errorf("error = %v, want schedule_not_found", b["error"])
		}
	})

	t.Run("returns 404 for unknown route", func(t *testing.T) {
		app := newDefaultApp()
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/unknown", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "not_found" {
			t.Errorf("error = %v, want not_found", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Role enforcement tests
// ---------------------------------------------------------------------------

func TestRoleEnforcement(t *testing.T) {
	t.Run("prevents non-manager schedule writes", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules", employeeHeaders,
			map[string]interface{}{"id": "schedule_denied", "name": "Denied"})
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "manager_approval_required" {
			t.Errorf("error = %v, want manager_approval_required", b["error"])
		}
	})

	t.Run("allows owner to write schedules", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules", ownerHeaders,
			map[string]interface{}{"id": "s_owner", "name": "Owner Created", "settings": map[string]interface{}{}})
		assertStatus(t, w, http.StatusCreated)
	})

	t.Run("allows employee to list schedules", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "t1", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)
		h := withTenant(employeeHeaders, "user_worker_1", "t1", auth.RoleEmployee)
		w := do(app, "GET", "/v1/tenants/t1/schedules", h, nil)
		assertStatus(t, w, http.StatusOK)
	})
}

// ---------------------------------------------------------------------------
// Schedule workflow tests (availability, drafts, publish, requests)
// ---------------------------------------------------------------------------

func TestScheduleWorkflows(t *testing.T) {
	seedSchedule := func(st store.Store) {
		st.PutSchedule(store.Schedule{
			ID: "s1", TenantID: "tenant_security_demo",
			Name: "X", Settings: map[string]interface{}{}, Status: "draft",
		})
	}

	t.Run("submits availability for a schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/availability",
			employeeHeaders, map[string]interface{}{"approvalId": "av_1"})
		assertStatus(t, w, http.StatusAccepted)
		b := jsonBody(t, w)
		if b["id"] != "av_1" {
			t.Errorf("id = %v, want av_1", b["id"])
		}
		if b["scheduleId"] != "s1" {
			t.Errorf("scheduleId = %v, want s1", b["scheduleId"])
		}
		if b["state"] != "pending" {
			t.Errorf("state = %v, want pending", b["state"])
		}
	})

	t.Run("submits availability with auto-generated id", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/availability",
			employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusAccepted)
		b := jsonBody(t, w)
		id, _ := b["id"].(string)
		if !strings.HasPrefix(id, "approval_") {
			t.Errorf("auto-generated id should start with 'approval_', got %q", id)
		}
	})

	t.Run("creates a draft for a schedule (manager only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/drafts",
			managerHeaders, nil)
		assertStatus(t, w, http.StatusCreated)
		b := jsonBody(t, w)
		id, _ := b["id"].(string)
		if !strings.HasPrefix(id, "draft_") {
			t.Errorf("draft id should start with 'draft_', got %q", id)
		}
		if b["scheduleId"] != "s1" {
			t.Errorf("scheduleId = %v, want s1", b["scheduleId"])
		}
		if b["createdAt"] == nil || b["createdAt"] == "" {
			t.Errorf("createdAt should be set")
		}
	})

	t.Run("prevents employee from creating a draft", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/drafts",
			employeeHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
	})

	t.Run("publishes a schedule (manager only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		st.PutDraft(store.Draft{
			ID: "draft_1", TenantID: "tenant_security_demo", ScheduleID: "s1",
			Shifts: []interface{}{}, CreatedBy: "user_mgr_1", CreatedAt: "2024-01-01T00:00:00Z",
		})
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/publish",
			managerHeaders, map[string]interface{}{"draftId": "draft_1"})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["scheduleId"] != "s1" {
			t.Errorf("scheduleId = %v, want s1", b["scheduleId"])
		}
		if b["draftId"] != "draft_1" {
			t.Errorf("draftId = %v, want draft_1", b["draftId"])
		}
		if b["publishedAt"] == nil || b["publishedAt"] == "" {
			t.Errorf("publishedAt should be set")
		}
		// Verify schedule was updated to published status.
		updated := st.GetSchedule("tenant_security_demo", "s1")
		if updated == nil || updated.Status != "published" {
			t.Errorf("schedule status should be published after publish, got %v", updated)
		}
	})

	t.Run("submits a request for a schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/requests",
			employeeHeaders, map[string]interface{}{"id": "req_1"})
		assertStatus(t, w, http.StatusAccepted)
		b := jsonBody(t, w)
		if b["id"] != "req_1" {
			t.Errorf("id = %v, want req_1", b["id"])
		}
		if b["scheduleId"] != "s1" {
			t.Errorf("scheduleId = %v, want s1", b["scheduleId"])
		}
		if b["state"] != "pending" {
			t.Errorf("state = %v, want pending", b["state"])
		}
	})

	t.Run("submits a request with auto-generated id", func(t *testing.T) {
		st := store.NewMemoryStore()
		seedSchedule(st)
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules/s1/requests",
			employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusAccepted)
		b := jsonBody(t, w)
		id, _ := b["id"].(string)
		if !strings.HasPrefix(id, "request_") {
			t.Errorf("auto-generated id should start with 'request_', got %q", id)
		}
	})
}

// ---------------------------------------------------------------------------
// Schedgy import tests
// ---------------------------------------------------------------------------

func TestSchedgy(t *testing.T) {
	t.Run("imports Schedgy approved constraints through Scheduler boundary", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedgy/approved-constraints:import",
			managerHeaders, map[string]interface{}{
				"sourceSystem": "schedgy",
				"approvedConstraints": []interface{}{
					map[string]interface{}{"constraint": map[string]interface{}{"id": "constraint_schedgy_1"}},
				},
			})
		assertStatus(t, w, http.StatusAccepted)
		b := jsonBody(t, w)
		ids, _ := b["importedConstraintIds"].([]interface{})
		if len(ids) != 1 || ids[0] != "constraint_schedgy_1" {
			t.Errorf("importedConstraintIds = %v, want [constraint_schedgy_1]", ids)
		}
		approvalState, _ := b["approvalState"].(map[string]interface{})
		if approvalState["state"] != "pending" {
			t.Errorf("approvalState.state = %v, want pending", approvalState["state"])
		}
	})

	t.Run("rejects schedgy import with wrong source system", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedgy/approved-constraints:import",
			managerHeaders, map[string]interface{}{
				"sourceSystem":        "other",
				"approvedConstraints": []interface{}{},
			})
		assertStatus(t, w, http.StatusBadRequest)
		b := jsonBody(t, w)
		if b["error"] != "invalid_argument" {
			t.Errorf("error = %v, want invalid_argument", b["error"])
		}
	})

	t.Run("rejects schedgy import with empty constraints", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedgy/approved-constraints:import",
			managerHeaders, map[string]interface{}{
				"sourceSystem":        "schedgy",
				"approvedConstraints": []interface{}{},
			})
		assertStatus(t, w, http.StatusBadRequest)
		b := jsonBody(t, w)
		if b["error"] != "invalid_argument" {
			t.Errorf("error = %v, want invalid_argument", b["error"])
		}
	})

	t.Run("prevents non-manager schedgy import", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedgy/approved-constraints:import",
			employeeHeaders, map[string]interface{}{
				"sourceSystem":        "schedgy",
				"approvedConstraints": []interface{}{},
			})
		assertStatus(t, w, http.StatusForbidden)
	})

	t.Run("gets import status for a schedgy import", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutImport(store.Import{
			ImportID:              "schedgy_import_123",
			TenantID:              "tenant_security_demo",
			SourceSystem:          "schedgy",
			ImportedConstraintIDs: []string{"c1", "c2"},
			ImportedCount:         2,
			CreatedAt:             100,
		})
		app := newApp(st)

		w := do(app, "GET",
			"/v1/tenants/tenant_security_demo/schedgy/imports/schedgy_import_123",
			employeeHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["importId"] != "schedgy_import_123" {
			t.Errorf("importId = %v, want schedgy_import_123", b["importId"])
		}
		if b["importedCount"] != float64(2) {
			t.Errorf("importedCount = %v, want 2", b["importedCount"])
		}
	})

	t.Run("returns 404 for non-existent import", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "GET",
			"/v1/tenants/tenant_security_demo/schedgy/imports/nonexistent",
			employeeHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "import_not_found" {
			t.Errorf("error = %v, want import_not_found", b["error"])
		}
	})

	t.Run("import status is tenant-scoped", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutImport(store.Import{
			ImportID:              "imp_1",
			TenantID:              "tenant_a",
			ImportedConstraintIDs: []string{},
			CreatedAt:             100,
		})
		app := newApp(st)

		// Request from tenant_security_demo for an import that belongs to tenant_a.
		w := do(app, "GET",
			"/v1/tenants/tenant_security_demo/schedgy/imports/imp_1",
			employeeHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("lists schedgy imports", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutImport(store.Import{ImportID: "imp_1", TenantID: "tenant_security_demo", ImportedConstraintIDs: []string{"c1"}, CreatedAt: 100})
		st.PutImport(store.Import{ImportID: "imp_2", TenantID: "tenant_security_demo", ImportedConstraintIDs: []string{"c2"}, CreatedAt: 200})
		st.PutImport(store.Import{ImportID: "imp_3", TenantID: "tenant_other", ImportedConstraintIDs: []string{"c3"}, CreatedAt: 300})
		app := newApp(st)

		w := do(app, "GET",
			"/v1/tenants/tenant_security_demo/schedgy/imports",
			employeeHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		items, _ := b["items"].([]interface{})
		if len(items) != 2 {
			t.Errorf("items length = %d, want 2", len(items))
		}
		// Newest first (createdAt 200 > 100).
		first, _ := items[0].(map[string]interface{})
		if first["importId"] != "imp_2" {
			t.Errorf("first item importId = %v, want imp_2", first["importId"])
		}
	})
}

// ---------------------------------------------------------------------------
// Tenant isolation (memory store)
// ---------------------------------------------------------------------------

func TestTenantIsolation(t *testing.T) {
	t.Run("memory store isolates tenants", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "a", Name: "A", Settings: map[string]interface{}{}, Status: "draft"})
		st.PutSchedule(store.Schedule{ID: "s2", TenantID: "b", Name: "B", Settings: map[string]interface{}{}, Status: "draft"})

		if got := len(st.ListSchedules("a")); got != 1 {
			t.Errorf("tenant a: ListSchedules = %d, want 1", got)
		}
		if got := len(st.ListSchedules("b")); got != 1 {
			t.Errorf("tenant b: ListSchedules = %d, want 1", got)
		}
		s := st.GetSchedule("a", "s1")
		if s == nil || s.Name != "A" {
			t.Errorf("GetSchedule(a, s1).Name = %v, want A", s)
		}
		if got := st.GetSchedule("a", "s2"); got != nil {
			t.Errorf("GetSchedule(a, s2) should be nil, got %v", got)
		}
	})

	t.Run("memory store imports are tenant-scoped", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutImport(store.Import{ImportID: "i1", TenantID: "a", ImportedConstraintIDs: []string{}})
		st.PutImport(store.Import{ImportID: "i2", TenantID: "a", ImportedConstraintIDs: []string{}})
		imp := st.PutImport(store.Import{ImportID: "i3", TenantID: "a", ImportedConstraintIDs: []string{"c1"}})
		if len(imp.ImportedConstraintIDs) != 1 || imp.ImportedConstraintIDs[0] != "c1" {
			t.Errorf("importedConstraintIds = %v, want [c1]", imp.ImportedConstraintIDs)
		}
	})
}

// ---------------------------------------------------------------------------
// Duplicate schedule overwrite
// ---------------------------------------------------------------------------

func TestScheduleOverwrite(t *testing.T) {
	t.Run("putSchedule overwrites existing schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "a", Name: "Old", Settings: map[string]interface{}{}, Status: "draft"})
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "a", Name: "New", Settings: map[string]interface{}{}, Status: "active"})

		s := st.GetSchedule("a", "s1")
		if s == nil {
			t.Fatal("expected schedule, got nil")
		}
		if s.Name != "New" {
			t.Errorf("Name = %v, want New", s.Name)
		}
		if s.Status != "active" {
			t.Errorf("Status = %v, want active", s.Status)
		}
	})
}

// ---------------------------------------------------------------------------
// PATCH schedule
// ---------------------------------------------------------------------------

func TestPatchSchedule(t *testing.T) {
	t.Run("updates a schedule (manager only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "Old Name", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)

		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s1",
			managerHeaders, map[string]interface{}{
				"updates": map[string]interface{}{"name": "New Name", "settings": map[string]interface{}{"timeZone": "UTC"}},
			})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["name"] != "New Name" {
			t.Errorf("name = %v, want New Name", b["name"])
		}
		settings, _ := b["settings"].(map[string]interface{})
		if settings["timeZone"] != "UTC" {
			t.Errorf("settings.timeZone = %v, want UTC", settings["timeZone"])
		}
	})

	t.Run("rejects update for non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/nonexistent",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "X"}})
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("prevents employee from updating schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s1",
			employeeHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "Y"}})
		assertStatus(t, w, http.StatusForbidden)
	})
}

// Duplicate-name detection must also apply to UPDATE paths (PATCH/PUT), not
// just CREATE — otherwise a rename can silently create a duplicate.
func TestUpdateDuplicateScheduleName(t *testing.T) {
	// Seed two schedules; renaming one onto the other's name must 409.
	seed := func() store.Store {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s_alpha", TenantID: "tenant_security_demo", Name: "Alpha", Settings: map[string]interface{}{}, Status: "draft"})
		st.PutSchedule(store.Schedule{ID: "s_beta", TenantID: "tenant_security_demo", Name: "Beta", Settings: map[string]interface{}{}, Status: "draft"})
		return st
	}

	t.Run("PATCH rename to another schedule's name -> 409", func(t *testing.T) {
		app := newApp(seed())
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s_beta",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "Alpha"}})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409, got %d: %s", w.Code, w.Body.String())
		}
		var b map[string]string
		json.NewDecoder(w.Body).Decode(&b)
		if b["error"] != "schedule_name_taken" {
			t.Errorf("want error=schedule_name_taken, got %q", b["error"])
		}
	})

	t.Run("PATCH rename case-insensitive duplicate -> 409", func(t *testing.T) {
		app := newApp(seed())
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s_beta",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "  alpha  "}})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409 (case/space-insensitive dup), got %d: %s", w.Code, w.Body.String())
		}
	})

	t.Run("PATCH rename to own name (and a variant) -> 200", func(t *testing.T) {
		app := newApp(seed())
		// Same name.
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s_alpha",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "Alpha"}})
		if w.Code != http.StatusOK {
			t.Fatalf("renaming to own name: want 200, got %d: %s", w.Code, w.Body.String())
		}
		// Case/space variant of own name, stored trimmed.
		w = do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s_alpha",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "  alpha  "}})
		if w.Code != http.StatusOK {
			t.Fatalf("renaming to own-name variant: want 200, got %d: %s", w.Code, w.Body.String())
		}
		var b map[string]interface{}
		json.NewDecoder(w.Body).Decode(&b)
		if b["name"] != "alpha" {
			t.Errorf("want stored trimmed name %q, got %q", "alpha", b["name"])
		}
	})

	t.Run("PATCH rename to whitespace-only -> 400", func(t *testing.T) {
		app := newApp(seed())
		w := do(app, "PATCH", "/v1/tenants/tenant_security_demo/schedules/s_beta",
			managerHeaders, map[string]interface{}{"updates": map[string]interface{}{"name": "   "}})
		if w.Code != http.StatusBadRequest {
			t.Fatalf("want 400, got %d: %s", w.Code, w.Body.String())
		}
	})

	t.Run("PUT rename to another schedule's name -> 409", func(t *testing.T) {
		app := newApp(seed())
		w := do(app, "PUT", "/v1/tenants/tenant_security_demo/schedules/s_beta",
			managerHeaders, map[string]interface{}{"name": "Alpha", "status": "draft"})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409, got %d: %s", w.Code, w.Body.String())
		}
	})

	t.Run("PUT rename to a unique name -> 200 stored trimmed", func(t *testing.T) {
		app := newApp(seed())
		w := do(app, "PUT", "/v1/tenants/tenant_security_demo/schedules/s_beta",
			managerHeaders, map[string]interface{}{"name": "  Gamma  ", "status": "draft"})
		if w.Code != http.StatusOK {
			t.Fatalf("want 200, got %d: %s", w.Code, w.Body.String())
		}
		var b map[string]interface{}
		json.NewDecoder(w.Body).Decode(&b)
		if b["name"] != "Gamma" {
			t.Errorf("want stored trimmed name %q, got %q", "Gamma", b["name"])
		}
	})
}

// ---------------------------------------------------------------------------
// DELETE schedule
// ---------------------------------------------------------------------------

func TestDeleteSchedule(t *testing.T) {
	t.Run("deletes a schedule (manager only)", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)

		w := do(app, "DELETE", "/v1/tenants/tenant_security_demo/schedules/s1", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["success"] != true {
			t.Errorf("success = %v, want true", b["success"])
		}
		if b["id"] != "s1" {
			t.Errorf("id = %v, want s1", b["id"])
		}
		if got := st.GetSchedule("tenant_security_demo", "s1"); got != nil {
			t.Errorf("schedule should be deleted, got %v", got)
		}
	})

	t.Run("returns 404 deleting non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "DELETE", "/v1/tenants/tenant_security_demo/schedules/nonexistent", managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("prevents employee from deleting schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)
		w := do(app, "DELETE", "/v1/tenants/tenant_security_demo/schedules/s1", employeeHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
	})
}

// ---------------------------------------------------------------------------
// PUT schedule (full replace)
// ---------------------------------------------------------------------------

func TestPutSchedule(t *testing.T) {
	t.Run("replaces a schedule via PUT", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "Old", Settings: map[string]interface{}{"a": float64(1)}, Status: "draft"})
		app := newApp(st)

		w := do(app, "PUT", "/v1/tenants/tenant_security_demo/schedules/s1",
			managerHeaders, map[string]interface{}{"name": "FullReplace", "status": "published"})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["name"] != "FullReplace" {
			t.Errorf("name = %v, want FullReplace", b["name"])
		}
		if b["status"] != "published" {
			t.Errorf("status = %v, want published", b["status"])
		}
		// Settings not supplied — should be preserved from existing.
		settings, _ := b["settings"].(map[string]interface{})
		if settings["a"] != float64(1) {
			t.Errorf("settings.a = %v, want 1", settings["a"])
		}
	})

	t.Run("returns 404 for PUT non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "PUT", "/v1/tenants/tenant_security_demo/schedules/nonexistent",
			managerHeaders, map[string]interface{}{"name": "X"})
		assertStatus(t, w, http.StatusNotFound)
	})
}

// ---------------------------------------------------------------------------
// Health / status endpoints
// ---------------------------------------------------------------------------

func TestHealth(t *testing.T) {
	t.Run("healthz returns ok", func(t *testing.T) {
		app := newDefaultApp()
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/healthz", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["status"] != "ok" {
			t.Errorf("status = %v, want ok", b["status"])
		}
		if b["service"] != "Scheduler" {
			t.Errorf("service = %v, want Scheduler", b["service"])
		}
	})

	t.Run("readyz returns ready", func(t *testing.T) {
		app := newDefaultApp()
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/readyz", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["ready"] != true {
			t.Errorf("ready = %v, want true", b["ready"])
		}
		checks, _ := b["checks"].([]interface{})
		if len(checks) != 1 {
			t.Errorf("checks length = %d, want 1", len(checks))
		}
	})

	t.Run("status returns service info", func(t *testing.T) {
		app := newDefaultApp()
		w := do(app, "GET", "/v1/tenants/tenant_security_demo/status", managerHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["service"] != "Scheduler" {
			t.Errorf("service = %v, want Scheduler", b["service"])
		}
		if b["dependencies"] == nil {
			t.Errorf("dependencies should be present")
		}
	})
}

// ---------------------------------------------------------------------------
// Schedule name validation
// ---------------------------------------------------------------------------

func TestScheduleValidation(t *testing.T) {
	t.Run("rejects schedule creation without name", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST", "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"settings": map[string]interface{}{}})
		assertStatus(t, w, http.StatusBadRequest)
		b := jsonBody(t, w)
		if b["error"] != "invalid_argument" {
			t.Errorf("error = %v, want invalid_argument", b["error"])
		}
	})

	t.Run("availability returns 404 for non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedules/nonexistent/availability",
			employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("draft returns 404 for non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedules/nonexistent/drafts",
			managerHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("publish requires draftId", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedules/s1/publish",
			managerHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusBadRequest)
	})

	t.Run("publish rejects non-existent draft", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{ID: "s1", TenantID: "tenant_security_demo", Name: "X", Settings: map[string]interface{}{}, Status: "draft"})
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedules/s1/publish",
			managerHeaders, map[string]interface{}{"draftId": "nonexistent"})
		assertStatus(t, w, http.StatusNotFound)
	})

	t.Run("request returns 404 for non-existent schedule", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		w := do(app, "POST",
			"/v1/tenants/tenant_security_demo/schedules/nonexistent/requests",
			employeeHeaders, map[string]interface{}{})
		assertStatus(t, w, http.StatusNotFound)
	})
}

// ---------------------------------------------------------------------------
// Concurrent ID uniqueness
// ---------------------------------------------------------------------------

// TestCreateScheduleConcurrentIDs fires n concurrent POST /schedules requests
// and asserts that every auto-generated ID is non-empty and unique.  It is
// designed to be run with the race detector (go test -race) to catch data
// races in ID generation.
func TestCreateScheduleConcurrentIDs(t *testing.T) {
	app := newDefaultApp()
	const n = 20
	ids := make([]string, n)
	var wg sync.WaitGroup
	var mu sync.Mutex
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
				managerHeaders, map[string]interface{}{"name": fmt.Sprintf("sched-%d", i)})
			if w.Code != http.StatusCreated {
				t.Errorf("request %d: want 201, got %d", i, w.Code)
				return
			}
			var resp map[string]interface{}
			_ = json.NewDecoder(w.Body).Decode(&resp)
			mu.Lock()
			ids[i], _ = resp["id"].(string)
			mu.Unlock()
		}(i)
	}
	wg.Wait()
	seen := make(map[string]bool)
	for _, id := range ids {
		if id == "" {
			t.Fatal("got empty id")
		}
		if seen[id] {
			t.Fatalf("duplicate id: %s", id)
		}
		seen[id] = true
	}
}

// ---------------------------------------------------------------------------
// Duplicate schedule name detection
// ---------------------------------------------------------------------------

func TestDuplicateScheduleName(t *testing.T) {
	// Duplicate name → 409
	t.Run("rejects duplicate schedule name", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID:       "s_existing",
			TenantID: "tenant_security_demo",
			Name:     "Night Shift",
			Settings: map[string]interface{}{},
			Status:   "draft",
		})
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "Night Shift"})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409, got %d: %s", w.Code, w.Body.String())
		}
		var body map[string]string
		json.NewDecoder(w.Body).Decode(&body)
		if body["error"] != "schedule_name_taken" {
			t.Errorf("want error=schedule_name_taken, got %q", body["error"])
		}
	})

	// Duplicate check is tenant-scoped — same name in different tenant is OK
	t.Run("allows same name in different tenant", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID:       "s_other",
			TenantID: "other_tenant",
			Name:     "Night Shift",
			Settings: map[string]interface{}{},
			Status:   "draft",
		})
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "Night Shift"})
		if w.Code != http.StatusCreated {
			t.Fatalf("want 201, got %d: %s", w.Code, w.Body.String())
		}
	})

	// Name comparison is case-insensitive — the server is the source of truth
	// and agrees with the iOS/Android/web clients, which all treat differing
	// case as the same name.
	t.Run("name comparison is case-insensitive", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID:       "s_ci",
			TenantID: "tenant_security_demo",
			Name:     "night shift",
			Settings: map[string]interface{}{},
			Status:   "draft",
		})
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "Night Shift"})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409 (case-insensitive dup), got %d: %s", w.Code, w.Body.String())
		}
	})

	// Surrounding whitespace is ignored for duplicate detection, so a padded
	// name cannot sneak past the 409 guard and create a near-duplicate.
	t.Run("name comparison ignores surrounding whitespace", func(t *testing.T) {
		st := store.NewMemoryStore()
		st.PutSchedule(store.Schedule{
			ID:       "s_ws",
			TenantID: "tenant_security_demo",
			Name:     "Night Shift",
			Settings: map[string]interface{}{},
			Status:   "draft",
		})
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "  Night Shift  "})
		if w.Code != http.StatusConflict {
			t.Fatalf("want 409 (whitespace-trimmed dup), got %d: %s", w.Code, w.Body.String())
		}
	})

	// The created schedule stores the trimmed name, not the padded input.
	t.Run("stores trimmed name", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "  Morning Shift  "})
		if w.Code != http.StatusCreated {
			t.Fatalf("want 201, got %d: %s", w.Code, w.Body.String())
		}
		var body map[string]interface{}
		json.NewDecoder(w.Body).Decode(&body)
		if body["name"] != "Morning Shift" {
			t.Errorf("want stored name %q, got %q", "Morning Shift", body["name"])
		}
	})

	// A name that is only whitespace is rejected as missing, not stored blank.
	t.Run("whitespace-only name is rejected", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, http.MethodPost, "/v1/tenants/tenant_security_demo/schedules",
			managerHeaders, map[string]interface{}{"name": "   "})
		if w.Code != http.StatusBadRequest {
			t.Fatalf("want 400, got %d: %s", w.Code, w.Body.String())
		}
		var body map[string]string
		json.NewDecoder(w.Body).Decode(&body)
		if body["error"] != "invalid_argument" {
			t.Errorf("want error=invalid_argument, got %q", body["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Rate limiting
// ---------------------------------------------------------------------------

func TestRateLimit(t *testing.T) {
	t.Run("rate limit slows burst above threshold", func(t *testing.T) {
		st := store.NewMemoryStore()
		rl := api.NewRateLimiter(3)
		app := api.NewHandler(st, rl, fakeVerifier{})

		url := "/v1/tenants/tenant_security_demo/schedules"
		for i := 0; i < 3; i++ {
			w := do(app, "GET", url, managerHeaders, nil)
			if w.Code != http.StatusOK {
				t.Errorf("request %d: status = %d, want 200", i+1, w.Code)
			}
		}

		w := do(app, "GET", url, managerHeaders, nil)
		assertStatus(t, w, http.StatusTooManyRequests)
		b := jsonBody(t, w)
		if b["error"] != "rate_limited" {
			t.Errorf("error = %v, want rate_limited", b["error"])
		}
	})
}
