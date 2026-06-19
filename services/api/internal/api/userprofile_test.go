package api_test

// userprofile_test.go exercises the user-profile / user-role domain end-to-end
// through the router: get + upsert of users/{uid} (display_name/title/role) and
// the role-only upsert. It reuses the helpers (do, jsonBody, assertStatus,
// *Headers, mergeHeaders) defined in api_test.go.
//
// The load-bearing security property here is IDENTITY OWNERSHIP (IDOR): a user
// may only upsert THEIR OWN profile/role — the {uid} in the path must equal the
// authenticated actor's uid, unless the actor is an admin. These tests pin that
// behaviour, plus the #19 contract that the written role comes from the request
// body (server-derived from the RoleStruct) and never from a client-trusted
// X-User-Role header.

import (
	"net/http"
	"testing"

	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

const upTenant = "tenant_security_demo"

// usersURL is the collection path for the demo tenant. The header fixtures in
// api_test.go all use tenant_security_demo, so paths must match for auth to pass.
func userURL(uid string) string {
	return "/v1/tenants/" + upTenant + "/users/" + uid
}

// managerHeaders → uid user_mgr_1 (role manager); employeeHeaders → uid
// user_worker_1 (role employee); ownerHeaders → uid user_owner_1 (role owner).

// ---------------------------------------------------------------------------
// Profile upsert (PUT /users/{uid}) — self path
// ---------------------------------------------------------------------------

func TestUserProfileUpsertSelf(t *testing.T) {
	t.Run("employee upserts their OWN profile", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "PUT", userURL("user_worker_1"), employeeHeaders, map[string]interface{}{
			"email":        "worker@acme.com",
			"display_name": "Wendy Worker",
			"title":        "Barista",
			"role":         map[string]interface{}{"is_worker": true},
		})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["uid"] != "user_worker_1" {
			t.Errorf("uid = %v, want user_worker_1", b["uid"])
		}
		if b["display_name"] != "Wendy Worker" {
			t.Errorf("display_name = %v, want Wendy Worker", b["display_name"])
		}
		// worker-only RoleStruct → Flutter string "employee" (verbatim mapping).
		if b["role"] != "employee" {
			t.Errorf("role = %v, want employee", b["role"])
		}
		if b["last_active_time"] == nil || b["last_active_time"] == "" {
			t.Errorf("last_active_time should be set, got %v", b["last_active_time"])
		}
	})

	t.Run("admin/creator RoleStruct → 'employer' (verbatim Flutter mapping)", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "PUT", userURL("user_mgr_1"), managerHeaders, map[string]interface{}{
			"email":        "mgr@acme.com",
			"display_name": "Mona Manager",
			"title":        "Owner",
			"role":         map[string]interface{}{"is_admin": true},
		})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["role"] != "employer" {
			t.Errorf("role = %v, want employer", b["role"])
		}
	})
}

// ---------------------------------------------------------------------------
// IDOR / authorization (the core security property)
// ---------------------------------------------------------------------------

func TestUserProfileIDOR(t *testing.T) {
	// A normal employee with valid tenant auth must NOT be able to upsert a
	// DIFFERENT user's profile. This is the core IDOR protection: tenant auth
	// alone does not let you edit someone else's identity doc.
	t.Run("employee cannot upsert ANOTHER user's profile -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		// employeeHeaders is uid user_worker_1, but the path targets user_victim.
		w := do(app, "PUT", userURL("user_victim"), employeeHeaders, map[string]interface{}{
			"display_name": "Hijacked",
			"role":         map[string]interface{}{"is_admin": true},
		})
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "not_profile_owner" {
			t.Errorf("error = %v, want not_profile_owner", b["error"])
		}
		// And the victim's doc must NOT have been created/modified.
		if p := st.GetUserProfile(upTenant, "user_victim"); p != nil {
			t.Errorf("victim profile must not exist after blocked write, got %+v", p)
		}
	})

	t.Run("employee cannot set ANOTHER user's role -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "PUT", userURL("user_victim")+"/role", employeeHeaders, map[string]interface{}{
			"role": map[string]interface{}{"is_admin": true},
		})
		assertStatus(t, w, http.StatusForbidden)
		if p := st.GetUserProfile(upTenant, "user_victim"); p != nil {
			t.Errorf("victim role must not be written, got %+v", p)
		}
	})

	t.Run("employee cannot READ another user's profile -> 403", func(t *testing.T) {
		st := store.NewMemoryStore()
		// Seed a profile for someone else.
		st.PutUserProfile(store.UserProfile{TenantID: upTenant, UID: "user_other", DisplayName: "Other"})
		app := newApp(st)
		w := do(app, "GET", userURL("user_other"), employeeHeaders, nil)
		assertStatus(t, w, http.StatusForbidden)
	})

	t.Run("admin (owner) MAY upsert another user's profile (override path)", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		// ownerHeaders is uid user_owner_1 acting on user_worker_1.
		w := do(app, "PUT", userURL("user_worker_1"), ownerHeaders, map[string]interface{}{
			"display_name": "Set By Admin",
			"role":         map[string]interface{}{"is_worker": true},
		})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["uid"] != "user_worker_1" {
			t.Errorf("uid = %v, want user_worker_1 (admin override)", b["uid"])
		}
		if b["display_name"] != "Set By Admin" {
			t.Errorf("display_name = %v, want Set By Admin", b["display_name"])
		}
	})
}

// ---------------------------------------------------------------------------
// No client-trusted role (#19 contract)
// ---------------------------------------------------------------------------

func TestUserProfileRoleNotHeaderTrusted(t *testing.T) {
	// An actor forging X-User-Role: owner does NOT cause "employer" to be
	// written. The written role is derived ONLY from the request-body RoleStruct
	// (is_worker → "employee" here), regardless of the header role.
	t.Run("forged X-User-Role does not change the written role", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		// Same uid (self), but spoof the role header to owner.
		spoofed := mergeHeaders(employeeHeaders, map[string]string{"X-User-Role": "owner"})
		w := do(app, "PUT", userURL("user_worker_1")+"/role", spoofed, map[string]interface{}{
			"email": "worker@acme.com",
			"role":  map[string]interface{}{"is_worker": true}, // body says employee
		})
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["role"] != "employee" {
			t.Errorf("role = %v, want employee (body-derived, not header-derived)", b["role"])
		}
	})
}

// ---------------------------------------------------------------------------
// Merge semantics (setDoc merge:true parity)
// ---------------------------------------------------------------------------

func TestUserProfileMergeSemantics(t *testing.T) {
	// The Choose-Role-before-name flow: role is written first, then a name-only
	// profile write must NOT clobber the previously chosen role, and vice-versa.
	t.Run("role-only write then name-only write preserves both", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)

		// Step 1: Choose-Role sets role only.
		r1 := do(app, "PUT", userURL("user_worker_1")+"/role", employeeHeaders, map[string]interface{}{
			"email": "w@acme.com",
			"role":  map[string]interface{}{"is_admin": true}, // employer
		})
		assertStatus(t, r1, http.StatusOK)

		// Step 2: name step sets display_name/title, NO role in the body.
		r2 := do(app, "PUT", userURL("user_worker_1"), employeeHeaders, map[string]interface{}{
			"display_name": "Named Later",
			"title":        "Lead",
		})
		assertStatus(t, r2, http.StatusOK)
		b := jsonBody(t, r2)
		if b["display_name"] != "Named Later" {
			t.Errorf("display_name = %v, want Named Later", b["display_name"])
		}
		// The role chosen in step 1 must survive the name-only write.
		if b["role"] != "employer" {
			t.Errorf("role = %v, want employer (preserved by merge)", b["role"])
		}
		// And the email from step 1 must survive too.
		if b["email"] != "w@acme.com" {
			t.Errorf("email = %v, want w@acme.com (preserved by merge)", b["email"])
		}
	})
}

// ---------------------------------------------------------------------------
// Get / not-found
// ---------------------------------------------------------------------------

func TestUserProfileGet(t *testing.T) {
	t.Run("get own profile after upsert", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		do(app, "PUT", userURL("user_worker_1"), employeeHeaders, map[string]interface{}{
			"display_name": "Self View", "role": map[string]interface{}{"is_worker": true},
		})
		w := do(app, "GET", userURL("user_worker_1"), employeeHeaders, nil)
		assertStatus(t, w, http.StatusOK)
		b := jsonBody(t, w)
		if b["display_name"] != "Self View" {
			t.Errorf("display_name = %v, want Self View", b["display_name"])
		}
	})

	t.Run("get own non-existent profile -> 404", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		w := do(app, "GET", userURL("user_worker_1"), employeeHeaders, nil)
		assertStatus(t, w, http.StatusNotFound)
		b := jsonBody(t, w)
		if b["error"] != "user_not_found" {
			t.Errorf("error = %v, want user_not_found", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Cross-tenant (auth layer) still applies
// ---------------------------------------------------------------------------

func TestUserProfileCrossTenant(t *testing.T) {
	t.Run("tenant in path must match auth tenant -> 403 tenant_mismatch", func(t *testing.T) {
		st := store.NewMemoryStore()
		app := newApp(st)
		// employeeHeaders carries X-Tenant-Id: tenant_security_demo, but the path
		// targets a different tenant.
		w := do(app, "PUT", "/v1/tenants/other_tenant/users/user_worker_1", employeeHeaders,
			map[string]interface{}{"display_name": "X"})
		assertStatus(t, w, http.StatusForbidden)
		b := jsonBody(t, w)
		if b["error"] != "tenant_mismatch" {
			t.Errorf("error = %v, want tenant_mismatch", b["error"])
		}
	})
}

// ---------------------------------------------------------------------------
// Store-level merge unit table (direct, no HTTP) — pins the per-field rules.
// ---------------------------------------------------------------------------

func TestUserProfileStoreMergeTable(t *testing.T) {
	cases := []struct {
		name      string
		seed      *store.UserProfile
		patch     store.UserProfile
		wantName  string
		wantTitle string
		wantRole  string
		wantEmail string
	}{
		{
			name:      "first write creates doc",
			patch:     store.UserProfile{TenantID: upTenant, UID: "u", Email: "a@x.com", DisplayName: "A", Title: "T", Role: "employee", LastActiveTime: "t1"},
			wantName:  "A",
			wantTitle: "T",
			wantRole:  "employee",
			wantEmail: "a@x.com",
		},
		{
			name:      "empty name in patch preserves stored name",
			seed:      &store.UserProfile{TenantID: upTenant, UID: "u", DisplayName: "Kept", Role: "employer"},
			patch:     store.UserProfile{TenantID: upTenant, UID: "u", DisplayName: "", Title: "NewTitle", LastActiveTime: "t2"},
			wantName:  "Kept",
			wantTitle: "NewTitle",
			wantRole:  "employer", // preserved (patch role empty)
		},
		{
			name:     "empty role in patch preserves stored role",
			seed:     &store.UserProfile{TenantID: upTenant, UID: "u", Role: "employer", DisplayName: "N"},
			patch:    store.UserProfile{TenantID: upTenant, UID: "u", DisplayName: "N2", LastActiveTime: "t3"},
			wantName: "N2",
			wantRole: "employer",
		},
		{
			name:     "non-empty role in patch overwrites stored role",
			seed:     &store.UserProfile{TenantID: upTenant, UID: "u", Role: "employee"},
			patch:    store.UserProfile{TenantID: upTenant, UID: "u", Role: "employer", LastActiveTime: "t4"},
			wantRole: "employer",
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			st := store.NewMemoryStore()
			if tc.seed != nil {
				st.PutUserProfile(*tc.seed)
			}
			got := st.PutUserProfile(tc.patch)
			if tc.wantName != "" && got.DisplayName != tc.wantName {
				t.Errorf("DisplayName = %q, want %q", got.DisplayName, tc.wantName)
			}
			if tc.wantTitle != "" && got.Title != tc.wantTitle {
				t.Errorf("Title = %q, want %q", got.Title, tc.wantTitle)
			}
			if tc.wantRole != "" && got.Role != tc.wantRole {
				t.Errorf("Role = %q, want %q", got.Role, tc.wantRole)
			}
			if tc.wantEmail != "" && got.Email != tc.wantEmail {
				t.Errorf("Email = %q, want %q", got.Email, tc.wantEmail)
			}
		})
	}
}
