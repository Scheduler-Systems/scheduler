// Package userprofile implements the HTTP handlers for the user-profile /
// user-role domain: get + upsert of the users/{uid} document (display name,
// title, role). It moves these writes off scheduler-web's Firestore-direct
// path (lib/firestore-write.ts upsertUserProfile / upsertUserRole) and behind
// the server-authoritative Go API.
//
// The load-bearing security property of this domain is IDENTITY OWNERSHIP: a
// user may only upsert THEIR OWN profile/role. The {uid} in the path must equal
// the authenticated actor's uid (the verified Firebase uid), otherwise the
// write is an IDOR — one user editing another user's identity doc. The only
// exception is an admin (owner/manager) acting on behalf of a user.
//
// Role is NEVER taken from a client-trusted header. It is computed server-side
// from the request body's RoleStruct (is_creator/is_admin/is_worker) using the
// SAME mapping scheduler-web uses (roleStructToFlutterString), so the value
// written to users/{uid}.role round-trips with the existing clients. A forged
// X-User-Role header cannot grant a role: the actor's header role only governs
// the admin-override path (may I write to a uid that isn't mine?), not the value
// written. This is the Go-side enforcement of the #19 verified-token contract.
package userprofile

import (
	"net/http"
	"strings"
	"time"

	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
	"github.com/Scheduler-Systems/scheduler-api/internal/store"
)

// now returns the current UTC time formatted as RFC3339. It mirrors the web
// client's serverTimestamp() write under the last_active_time key.
func now() string {
	return time.Now().UTC().Format(time.RFC3339)
}

// roleStructInput mirrors the web/Flutter RoleStruct (snake_case keys) so the
// API accepts the same JSON the web client already produces.
type roleStructInput struct {
	IsCreator bool `json:"is_creator"`
	IsAdmin   bool `json:"is_admin"`
	IsWorker  bool `json:"is_worker"`
}

// toFlutterRoleString maps a RoleStruct to the Flutter role string VERBATIM as
// scheduler-web's roleStructToFlutterString does: an admin or creator is an
// "employer", everyone else is an "employee".
func (r roleStructInput) toFlutterRoleString() string {
	if r.IsAdmin || r.IsCreator {
		return store.RoleEmployer
	}
	return store.RoleEmployee
}

// profileInput is the wire shape for PUT /users/{uid}. It mirrors the web
// UserProfileInput plus the email the client passes alongside the uid. role is
// optional: in the Flutter-aligned flow the role is chosen on the separate
// Choose-Role step BEFORE the name step, so a name/title write must not be
// required to carry (or clobber) the role.
type profileInput struct {
	Email       string           `json:"email"`
	DisplayName string           `json:"display_name"`
	Title       string           `json:"title"`
	Role        *roleStructInput `json:"role"`
}

// roleInput is the wire shape for PUT /users/{uid}/role — the role-only step.
type roleInput struct {
	Email string          `json:"email"`
	Role  roleStructInput `json:"role"`
}

// isAdmin reports whether the actor's role permits acting on another user's
// identity doc. Mirrors the manager/owner boundary used elsewhere (it reuses
// the auth role constants so the boundary stays in sync). The role here
// originates from the gateway/verified token (see api/auth.go) — on the #19
// branch it is derived from the verified token, so this boundary cannot be
// forged.
func isAdmin(actor httputil.Actor) bool {
	return auth.HasManagerBoundary(auth.Role(actor.Role))
}

// requireSelfOrAdmin writes a 403 and returns false when the actor is neither
// the owner of the target uid nor an admin. This is the IDOR-safe access check:
// passing tenant auth is NOT sufficient to mutate an arbitrary user's profile —
// the actor must BE that user, or be an admin acting on their behalf.
func requireSelfOrAdmin(w http.ResponseWriter, actor httputil.Actor, targetUID string) bool {
	if actor.UserID != "" && actor.UserID == targetUID {
		return true
	}
	if isAdmin(actor) {
		return true
	}
	httputil.WriteJSON(w, http.StatusForbidden, map[string]string{
		"error":   "not_profile_owner",
		"message": "a user may only modify their own profile",
	})
	return false
}

// GetHandler handles GET /v1/tenants/{tenantId}/users/{uid}
//
// Self-or-admin gated (a profile doc is private to its owner). Returns the
// stored users/{uid} doc, or 404 user_not_found if no profile has been written.
func GetHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		uid := params["uid"]
		if !requireSelfOrAdmin(w, actor, uid) {
			return
		}
		p := st.GetUserProfile(params["tenantId"], uid)
		if p == nil {
			httputil.WriteJSON(w, http.StatusNotFound, map[string]string{"error": "user_not_found"})
			return
		}
		httputil.WriteJSON(w, http.StatusOK, p)
	}
}

// UpsertProfileHandler handles PUT /v1/tenants/{tenantId}/users/{uid}
//
// Mirrors scheduler-web lib/firestore-write.ts upsertUserProfile. Writes
// display_name/title (+ optional role) onto users/{uid} with merge semantics:
// fields the client omits are preserved, so a name write never wipes a
// previously chosen role/email.
//
// IDOR-safe: the {uid} must be the actor's own uid (or the actor is an admin).
func UpsertProfileHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		uid := params["uid"]
		if !requireSelfOrAdmin(w, actor, uid) {
			return
		}

		var in profileInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		patch := store.UserProfile{
			TenantID:       params["tenantId"],
			UID:            uid,
			Email:          strings.TrimSpace(in.Email),
			DisplayName:    strings.TrimSpace(in.DisplayName),
			Title:          strings.TrimSpace(in.Title),
			LastActiveTime: now(),
		}
		// Role is server-derived from the body's RoleStruct, never from a
		// client header. When the body omits role, leave patch.Role empty so the
		// merge preserves any previously chosen role (Choose-Role-before-name
		// flow). A self (non-admin) actor may still set their own role here —
		// that is legitimate self-service onboarding, not privilege escalation,
		// because the role only governs this user's own employer/employee label.
		if in.Role != nil {
			patch.Role = in.Role.toFlutterRoleString()
		}

		stored := st.PutUserProfile(patch)
		httputil.WriteJSON(w, http.StatusOK, stored)
	}
}

// UpsertRoleHandler handles PUT /v1/tenants/{tenantId}/users/{uid}/role
//
// Mirrors scheduler-web lib/firestore-write.ts upsertUserRole — the Choose-Role
// step. Writes ONLY the role (+ identity + last_active_time) onto users/{uid},
// leaving name/title untouched via merge.
//
// SECURITY (#19 contract): the written role is computed server-side from the
// request body's RoleStruct, NOT trusted from any client-supplied X-User-Role
// header. The actor's header/token role only gates the admin-override path
// (may I set the role on a uid that isn't mine?). A non-admin may set their OWN
// role; only an admin may set another user's role.
func UpsertRoleHandler(st store.Store) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		params := httputil.ParamsFromContext(r.Context())
		actor := httputil.ActorFromContext(r.Context())
		uid := params["uid"]
		if !requireSelfOrAdmin(w, actor, uid) {
			return
		}

		var in roleInput
		if err := httputil.ReadJSON(r, &in); err != nil {
			httputil.WriteJSON(w, http.StatusBadRequest, map[string]string{
				"error": "bad_request", "message": err.Error(),
			})
			return
		}

		patch := store.UserProfile{
			TenantID:       params["tenantId"],
			UID:            uid,
			Email:          strings.TrimSpace(in.Email),
			Role:           in.Role.toFlutterRoleString(),
			LastActiveTime: now(),
		}
		stored := st.PutUserProfile(patch)
		httputil.WriteJSON(w, http.StatusOK, stored)
	}
}
