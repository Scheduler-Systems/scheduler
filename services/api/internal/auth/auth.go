// Package auth verifies Firebase ID tokens and derives the authenticated
// actor's identity and role from the *verified* token claims.
//
// # SECURITY CONTRACT
//
// The actor's identity (user id, tenant id) and role MUST be derived only from
// a cryptographically verified Firebase ID token — never from a client-supplied
// header such as X-User-Role / X-User-Id / X-Tenant-Id. Trusting those headers
// is a privilege-escalation vulnerability (any client could self-claim
// manager/owner). See issue #19.
package auth

import (
	"context"
	"errors"
	"strings"
)

// Role is the normalized authorization role used by the API's approval
// boundary. It is derived from verified token claims, not from client input.
type Role string

const (
	RoleEmployee Role = "employee"
	RoleManager  Role = "manager"
	RoleOwner    Role = "owner"
)

// Token is the verified, trusted actor context extracted from a Firebase ID
// token. Every field here originates from a verified signature — none of it is
// client-controlled plaintext.
type Token struct {
	// UserID is the Firebase uid (the token's "sub" / "user_id" claim).
	UserID string
	// TenantID is the tenant the user belongs to, taken from a verified custom
	// claim. It is NOT read from the X-Tenant-Id request header.
	TenantID string
	// Role is the normalized authorization role derived from a verified custom
	// claim. It is NOT read from the X-User-Role request header.
	Role Role
}

// Common verification errors. Callers translate these into HTTP statuses.
var (
	// ErrInvalidToken means the bearer token failed verification (bad
	// signature, wrong issuer/audience, expired, malformed, etc.).
	ErrInvalidToken = errors.New("invalid_token")
	// ErrMissingClaim means a required claim (uid or tenant) was absent.
	ErrMissingClaim = errors.New("missing_token_claim")
)

// Verifier verifies a raw Firebase ID token string and returns the trusted
// actor context. Implementations MUST validate the token's signature and
// standard claims before returning a non-error result.
type Verifier interface {
	Verify(ctx context.Context, idToken string) (*Token, error)
}

// NormalizeRole maps a raw Firebase custom-claim role value onto the API's
// authorization roles. The Scheduler user model stores "employer"/"employee";
// "owner" is the tenant owner. Anything unrecognized (including empty) is
// treated as the least-privileged role: employee. This is fail-closed by
// design — an unexpected claim value must never grant manager/owner rights.
func NormalizeRole(raw string) Role {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "owner":
		return RoleOwner
	// "employer" is the Scheduler term for a manager-equivalent user; "manager"
	// is accepted as a synonym for forward-compatibility.
	case "employer", "manager":
		return RoleManager
	default:
		return RoleEmployee
	}
}

// HasManagerBoundary reports whether the role is permitted to perform
// manager-only actions (schedule create/update/delete/publish, draft creation,
// Schedgy imports). Owners are a superset of managers.
func HasManagerBoundary(role Role) bool {
	return role == RoleManager || role == RoleOwner
}
