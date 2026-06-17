package auth

import (
	"context"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// googleCertsURL is the public endpoint serving the x509 certificates Google
// uses to sign Firebase ID tokens. The signing keys rotate, so the certs are
// cached with respect to the response Cache-Control max-age.
const googleCertsURL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

// FirebaseVerifier verifies Firebase ID tokens issued for a single Firebase
// project. It checks the RS256 signature against Google's rotating public certs
// and validates the standard Firebase claims (iss, aud, exp, iat, sub).
//
// It implements Verifier.
type FirebaseVerifier struct {
	projectID string
	certsURL  string
	httpc     *http.Client

	// roleClaim and tenantClaim name the custom claims that carry the actor's
	// role and tenant. Defaults are "role" and "tenant_id".
	roleClaim   string
	tenantClaim string

	mu       sync.RWMutex
	certs    map[string]*rsa.PublicKey
	certsExp time.Time
	nowFunc  func() time.Time
}

// FirebaseVerifierOption configures a FirebaseVerifier.
type FirebaseVerifierOption func(*FirebaseVerifier)

// WithHTTPClient overrides the HTTP client used to fetch signing certs.
func WithHTTPClient(c *http.Client) FirebaseVerifierOption {
	return func(v *FirebaseVerifier) { v.httpc = c }
}

// WithCertsURL overrides the cert endpoint (used in tests).
func WithCertsURL(u string) FirebaseVerifierOption {
	return func(v *FirebaseVerifier) { v.certsURL = u }
}

// WithClaimNames overrides the custom claim names for role and tenant.
func WithClaimNames(roleClaim, tenantClaim string) FirebaseVerifierOption {
	return func(v *FirebaseVerifier) {
		if roleClaim != "" {
			v.roleClaim = roleClaim
		}
		if tenantClaim != "" {
			v.tenantClaim = tenantClaim
		}
	}
}

// NewFirebaseVerifier constructs a verifier for the given Firebase project id.
func NewFirebaseVerifier(projectID string, opts ...FirebaseVerifierOption) *FirebaseVerifier {
	v := &FirebaseVerifier{
		projectID:   projectID,
		certsURL:    googleCertsURL,
		httpc:       &http.Client{Timeout: 10 * time.Second},
		roleClaim:   "role",
		tenantClaim: "tenant_id",
		certs:       map[string]*rsa.PublicKey{},
		nowFunc:     time.Now,
	}
	for _, o := range opts {
		o(v)
	}
	return v
}

// Verify validates the signature and claims of a Firebase ID token and returns
// the trusted actor context. It never trusts any request header — the entire
// returned Token is derived from the verified JWT.
func (v *FirebaseVerifier) Verify(ctx context.Context, idToken string) (*Token, error) {
	if idToken == "" {
		return nil, ErrInvalidToken
	}

	claims := jwt.MapClaims{}
	parser := jwt.NewParser(
		jwt.WithValidMethods([]string{"RS256"}),
		jwt.WithIssuer(fmt.Sprintf("https://securetoken.google.com/%s", v.projectID)),
		jwt.WithAudience(v.projectID),
		jwt.WithExpirationRequired(),
		jwt.WithTimeFunc(v.nowFunc),
	)

	_, err := parser.ParseWithClaims(idToken, claims, func(t *jwt.Token) (interface{}, error) {
		kid, _ := t.Header["kid"].(string)
		if kid == "" {
			return nil, fmt.Errorf("%w: missing kid", ErrInvalidToken)
		}
		key, err := v.keyForKID(ctx, kid)
		if err != nil {
			return nil, err
		}
		return key, nil
	})
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidToken, err)
	}

	// Firebase requires sub == user_id and a non-empty auth_time; sub is the
	// canonical uid. We treat sub as the source of truth for the user id.
	uid, _ := claims["sub"].(string)
	if uid == "" {
		// Some emulator tokens place the uid in user_id instead of sub.
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

// keyForKID returns the RSA public key for the given key id, refreshing the
// cached cert set if necessary.
func (v *FirebaseVerifier) keyForKID(ctx context.Context, kid string) (*rsa.PublicKey, error) {
	v.mu.RLock()
	key, ok := v.certs[kid]
	fresh := v.nowFunc().Before(v.certsExp)
	v.mu.RUnlock()
	if ok && fresh {
		return key, nil
	}

	if err := v.refreshCerts(ctx); err != nil {
		return nil, err
	}

	v.mu.RLock()
	defer v.mu.RUnlock()
	key, ok = v.certs[kid]
	if !ok {
		return nil, fmt.Errorf("%w: unknown signing key %q", ErrInvalidToken, kid)
	}
	return key, nil
}

// refreshCerts fetches and parses the current Google signing certificates.
func (v *FirebaseVerifier) refreshCerts(ctx context.Context) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, v.certsURL, nil)
	if err != nil {
		return err
	}
	resp, err := v.httpc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("fetch certs: status %d", resp.StatusCode)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return err
	}

	var raw map[string]string
	if err := json.Unmarshal(body, &raw); err != nil {
		return err
	}

	parsed := make(map[string]*rsa.PublicKey, len(raw))
	for kid, certPEM := range raw {
		block, _ := pem.Decode([]byte(certPEM))
		if block == nil {
			continue
		}
		cert, err := x509.ParseCertificate(block.Bytes)
		if err != nil {
			continue
		}
		pub, ok := cert.PublicKey.(*rsa.PublicKey)
		if !ok {
			continue
		}
		parsed[kid] = pub
	}
	if len(parsed) == 0 {
		return fmt.Errorf("fetch certs: no usable RSA keys")
	}

	// Respect Cache-Control max-age; default to 1h if unparsable.
	ttl := time.Hour
	if cc := resp.Header.Get("Cache-Control"); cc != "" {
		if d, ok := maxAge(cc); ok {
			ttl = d
		}
	}

	v.mu.Lock()
	v.certs = parsed
	v.certsExp = v.nowFunc().Add(ttl)
	v.mu.Unlock()
	return nil
}
