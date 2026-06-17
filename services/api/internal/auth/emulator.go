package auth

import (
	"context"
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// EmulatorVerifier verifies tokens issued by the Firebase Auth emulator, which
// signs ID tokens with alg "none" (unsigned). It still enforces issuer,
// audience and expiry so the actor context is well-formed, and it derives
// identity/role/tenant from the *token claims*, not request headers.
//
// SECURITY: This verifier accepts unsigned tokens and therefore MUST ONLY be
// wired when the process is explicitly pointed at the Auth emulator
// (FIREBASE_AUTH_EMULATOR_HOST is set). Production wiring uses FirebaseVerifier,
// which requires a valid RS256 signature. It implements Verifier.
type EmulatorVerifier struct {
	projectID   string
	roleClaim   string
	tenantClaim string
	nowFunc     func() time.Time
}

// NewEmulatorVerifier constructs an emulator verifier for the given project id.
func NewEmulatorVerifier(projectID string) *EmulatorVerifier {
	return &EmulatorVerifier{
		projectID:   projectID,
		roleClaim:   "role",
		tenantClaim: "tenant_id",
		nowFunc:     time.Now,
	}
}

// Verify parses an emulator (unsigned) ID token and validates its claims.
func (v *EmulatorVerifier) Verify(_ context.Context, idToken string) (*Token, error) {
	if idToken == "" {
		return nil, ErrInvalidToken
	}

	claims := jwt.MapClaims{}
	parser := jwt.NewParser(
		// The emulator uses the "none" algorithm (unsigned).
		jwt.WithValidMethods([]string{"none"}),
		jwt.WithIssuer(fmt.Sprintf("https://securetoken.google.com/%s", v.projectID)),
		jwt.WithAudience(v.projectID),
		jwt.WithExpirationRequired(),
		jwt.WithTimeFunc(v.nowFunc),
	)
	if _, err := parser.ParseWithClaims(idToken, claims, func(*jwt.Token) (interface{}, error) {
		return jwt.UnsafeAllowNoneSignatureType, nil
	}); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}

	uid, _ := claims["sub"].(string)
	if uid == "" {
		uid, _ = claims["user_id"].(string)
	}
	if uid == "" {
		return nil, ErrMissingClaim
	}
	tenantID, _ := claims[v.tenantClaim].(string)
	if tenantID == "" {
		return nil, ErrMissingClaim
	}
	roleRaw, _ := claims[v.roleClaim].(string)

	return &Token{
		UserID:   uid,
		TenantID: tenantID,
		Role:     NormalizeRole(roleRaw),
	}, nil
}
