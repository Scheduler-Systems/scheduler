// Package api contains the HTTP routing, auth, middleware, and request/response
// helpers for the scheduler-api service.
package api

import (
	"errors"
	"net/http"
	"strings"

	"github.com/Scheduler-Systems/scheduler-api/internal/auth"
	"github.com/Scheduler-Systems/scheduler-api/internal/httputil"
)

// authResult is the internal return type from Authenticate.
type authResult struct {
	OK     bool
	Status int
	Error  string
	Actor  httputil.Actor
}

// Authenticate validates the inbound request and returns an authResult.
//
// SECURITY (issue #19): the actor's identity (user id, tenant id) AND role are
// derived ONLY from the verified Firebase ID token in the Authorization bearer
// header. Client-supplied headers (X-User-Role, X-User-Id, X-Tenant-Id) are
// NOT trusted for any authority decision — a forged X-User-Role: owner does not
// grant owner privileges.
//
// Rules:
//   - Authorization header must start with "Bearer " → 401 missing_bearer_token
//   - The bearer token must verify (signature + iss/aud/exp + uid/tenant
//     claims) → 401 invalid_token on failure
//   - The token's tenant claim must match the {tenantId} path param
//     → 403 tenant_mismatch
//   - X-Correlation-Id must be present (tracing only, not an authority source)
//     → 400 missing_actor_context
func Authenticate(r *http.Request, tenantID string, verifier auth.Verifier) authResult {
	authorization := r.Header.Get("Authorization")
	if !strings.HasPrefix(authorization, "Bearer ") {
		return authResult{OK: false, Status: http.StatusUnauthorized, Error: "missing_bearer_token"}
	}
	rawToken := strings.TrimSpace(strings.TrimPrefix(authorization, "Bearer "))

	// Identity, tenant, and role come from the VERIFIED token only.
	tok, err := verifier.Verify(r.Context(), rawToken)
	if err != nil {
		// Both signature/claim failures map to 401; the actor never gets to
		// pick its own identity or role from headers.
		switch {
		case errors.Is(err, auth.ErrMissingClaim):
			return authResult{OK: false, Status: http.StatusUnauthorized, Error: "invalid_token"}
		default:
			return authResult{OK: false, Status: http.StatusUnauthorized, Error: "invalid_token"}
		}
	}

	// Cross-tenant protection: the tenant is taken from the verified token, not
	// from the X-Tenant-Id header, and must match the path tenant.
	if tok.TenantID == "" || tok.TenantID != tenantID {
		return authResult{OK: false, Status: http.StatusForbidden, Error: "tenant_mismatch"}
	}

	// X-Correlation-Id is used purely for request tracing/audit. It carries no
	// authority, so it remains a header.
	correlationID := r.Header.Get("X-Correlation-Id")
	if correlationID == "" {
		return authResult{OK: false, Status: http.StatusBadRequest, Error: "missing_actor_context"}
	}

	// Identity, tenant, and role come from the VERIFIED token only (#19 — the
	// auth contract from fix/round1-auth-contract wins).
	//
	// Email is read from a gateway-injected header. It is optional and used
	// ONLY to authorize the invitee of an email-only invitation (normalized
	// match against the invitation's identification) — never to grant access
	// on its own. A future iteration derives it from the verified Bearer-token
	// claims (#19).
	return authResult{
		OK: true,
		Actor: httputil.Actor{
			TenantID:      tok.TenantID,
			UserID:        tok.UserID,
			Email:         strings.TrimSpace(r.Header.Get("X-User-Email")),
			Role:          string(tok.Role),
			CorrelationID: correlationID,
		},
	}
}

// HasManagerApprovalBoundary returns true when the actor's role permits
// manager-only actions (manager or owner). The role originates from the
// verified token, so this boundary cannot be bypassed via request headers.
func HasManagerApprovalBoundary(actor httputil.Actor) bool {
	return auth.HasManagerBoundary(auth.Role(actor.Role))
}
