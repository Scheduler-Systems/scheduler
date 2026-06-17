package auth

import (
	"context"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"math/big"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const testProject = "your-firebase-project-id"

// testSigner holds an RSA key and serves its public cert at /certs so the
// FirebaseVerifier can fetch it exactly like Google's endpoint.
type testSigner struct {
	key    *rsa.PrivateKey
	kid    string
	server *httptest.Server
}

func newTestSigner(t *testing.T) *testSigner {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("genkey: %v", err)
	}
	kid := "test-kid-1"

	// Build a self-signed cert wrapping the public key.
	tmpl := &x509.Certificate{
		SerialNumber: big.NewInt(1),
		Subject:      pkix.Name{CommonName: "securetoken-test"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(time.Hour),
	}
	der, err := x509.CreateCertificate(rand.Reader, tmpl, tmpl, &key.PublicKey, key)
	if err != nil {
		t.Fatalf("create cert: %v", err)
	}
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})

	mux := http.NewServeMux()
	mux.HandleFunc("/certs", func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Cache-Control", "public, max-age=3600")
		_ = json.NewEncoder(w).Encode(map[string]string{kid: string(certPEM)})
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)

	return &testSigner{key: key, kid: kid, server: srv}
}

// sign produces a Firebase-shaped RS256 ID token with the given claims.
func (s *testSigner) sign(t *testing.T, claims jwt.MapClaims) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	tok.Header["kid"] = s.kid
	str, err := tok.SignedString(s.key)
	if err != nil {
		t.Fatalf("sign: %v", err)
	}
	return str
}

// validClaims returns a baseline set of valid Firebase claims for testProject.
func validClaims(uid, tenant, role string) jwt.MapClaims {
	now := time.Now()
	return jwt.MapClaims{
		"iss":       fmt.Sprintf("https://securetoken.google.com/%s", testProject),
		"aud":       testProject,
		"sub":       uid,
		"user_id":   uid,
		"auth_time": now.Add(-time.Minute).Unix(),
		"iat":       now.Add(-time.Minute).Unix(),
		"exp":       now.Add(time.Hour).Unix(),
		"tenant_id": tenant,
		"role":      role,
	}
}

func newVerifier(s *testSigner) *FirebaseVerifier {
	return NewFirebaseVerifier(testProject, WithCertsURL(s.server.URL+"/certs"))
}

// Core: role + identity are derived from the verified token claims.
func TestFirebaseVerifier_DerivesRoleAndIdentityFromToken(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)

	cases := []struct {
		name     string
		roleRaw  string
		wantRole Role
	}{
		{"employer maps to manager", "employer", RoleManager},
		{"manager synonym", "manager", RoleManager},
		{"owner", "owner", RoleOwner},
		{"employee", "employee", RoleEmployee},
		{"unknown fails closed to employee", "superadmin", RoleEmployee},
		{"empty fails closed to employee", "", RoleEmployee},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			tokStr := s.sign(t, validClaims("uid_123", "tenant_a", c.roleRaw))
			got, err := v.Verify(context.Background(), tokStr)
			if err != nil {
				t.Fatalf("verify: %v", err)
			}
			if got.UserID != "uid_123" {
				t.Errorf("UserID = %q, want uid_123", got.UserID)
			}
			if got.TenantID != "tenant_a" {
				t.Errorf("TenantID = %q, want tenant_a", got.TenantID)
			}
			if got.Role != c.wantRole {
				t.Errorf("Role = %q, want %q", got.Role, c.wantRole)
			}
		})
	}
}

// A token signed by a DIFFERENT key (forged signature) must be rejected — this
// is what stops a client from minting its own "owner" token.
func TestFirebaseVerifier_RejectsForgedSignature(t *testing.T) {
	good := newTestSigner(t)
	v := newVerifier(good)

	// Sign with an attacker key not served by the cert endpoint, but reuse the
	// good kid so the verifier looks up a (mismatched) key.
	attacker := newTestSigner(t)
	attacker.kid = good.kid
	forged := attacker.sign(t, validClaims("attacker", "tenant_a", "owner"))

	if _, err := v.Verify(context.Background(), forged); err == nil {
		t.Fatal("forged-signature token was accepted; signature not verified")
	}
}

func TestFirebaseVerifier_RejectsWrongAudience(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)
	claims := validClaims("uid", "tenant_a", "owner")
	claims["aud"] = "some-other-project"
	if _, err := v.Verify(context.Background(), s.sign(t, claims)); err == nil {
		t.Fatal("token with wrong audience was accepted")
	}
}

func TestFirebaseVerifier_RejectsWrongIssuer(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)
	claims := validClaims("uid", "tenant_a", "owner")
	claims["iss"] = "https://evil.example.com/" + testProject
	if _, err := v.Verify(context.Background(), s.sign(t, claims)); err == nil {
		t.Fatal("token with wrong issuer was accepted")
	}
}

func TestFirebaseVerifier_RejectsExpired(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)
	claims := validClaims("uid", "tenant_a", "owner")
	claims["exp"] = time.Now().Add(-time.Minute).Unix()
	if _, err := v.Verify(context.Background(), s.sign(t, claims)); err == nil {
		t.Fatal("expired token was accepted")
	}
}

// alg=none must be rejected by the production verifier (a classic JWT bypass).
func TestFirebaseVerifier_RejectsNoneAlg(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)
	tok := jwt.NewWithClaims(jwt.SigningMethodNone, validClaims("uid", "tenant_a", "owner"))
	str, err := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
	if err != nil {
		t.Fatalf("sign none: %v", err)
	}
	if _, err := v.Verify(context.Background(), str); err == nil {
		t.Fatal("alg=none token was accepted by production verifier")
	}
}

func TestFirebaseVerifier_RejectsMissingClaims(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)

	// Missing uid (sub + user_id empty).
	c1 := validClaims("", "tenant_a", "owner")
	delete(c1, "sub")
	delete(c1, "user_id")
	if _, err := v.Verify(context.Background(), s.sign(t, c1)); err == nil {
		t.Error("token missing uid was accepted")
	}

	// Missing tenant.
	c2 := validClaims("uid", "", "owner")
	delete(c2, "tenant_id")
	if _, err := v.Verify(context.Background(), s.sign(t, c2)); err == nil {
		t.Error("token missing tenant was accepted")
	}
}

func TestFirebaseVerifier_RejectsGarbage(t *testing.T) {
	s := newTestSigner(t)
	v := newVerifier(s)
	for _, raw := range []string{"", "not.a.jwt", "Bearer x"} {
		if _, err := v.Verify(context.Background(), raw); err == nil {
			t.Errorf("garbage token %q was accepted", raw)
		}
	}
}

// Emulator verifier accepts unsigned tokens but still validates claims and
// derives role/identity from the token.
func TestEmulatorVerifier_DerivesFromUnsignedToken(t *testing.T) {
	v := NewEmulatorVerifier(testProject)
	claims := validClaims("emu_uid", "tenant_emu", "employer")
	tok := jwt.NewWithClaims(jwt.SigningMethodNone, claims)
	str, err := tok.SignedString(jwt.UnsafeAllowNoneSignatureType)
	if err != nil {
		t.Fatalf("sign none: %v", err)
	}
	got, err := v.Verify(context.Background(), str)
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if got.UserID != "emu_uid" || got.TenantID != "tenant_emu" || got.Role != RoleManager {
		t.Errorf("got %+v, want uid=emu_uid tenant=tenant_emu role=manager", got)
	}
}

func TestNormalizeRole(t *testing.T) {
	cases := map[string]Role{
		"owner": RoleOwner, "OWNER": RoleOwner,
		"employer": RoleManager, "manager": RoleManager, " Manager ": RoleManager,
		"employee": RoleEmployee, "": RoleEmployee, "root": RoleEmployee, "admin": RoleEmployee,
	}
	for in, want := range cases {
		if got := NormalizeRole(in); got != want {
			t.Errorf("NormalizeRole(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestHasManagerBoundary(t *testing.T) {
	if !HasManagerBoundary(RoleManager) || !HasManagerBoundary(RoleOwner) {
		t.Error("manager/owner should have manager boundary")
	}
	if HasManagerBoundary(RoleEmployee) || HasManagerBoundary(Role("anything")) {
		t.Error("employee/unknown must NOT have manager boundary")
	}
}
