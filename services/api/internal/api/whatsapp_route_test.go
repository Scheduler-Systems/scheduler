package api_test

// whatsapp_route_test.go verifies that the report-only WhatsApp webhook routes
// are wired at the top level and BYPASS the tenant Bearer/role middleware — Meta
// is unauthenticated from the tenant model's perspective and authenticates only
// via the verify token (GET) or the per-request HMAC signature (POST).

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"testing"
)

func sign(secret string, body []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(body)
	return "sha256=" + hex.EncodeToString(mac.Sum(nil))
}

// rawDo sends a request without the tenant auth headers — exactly what Meta
// would send — and returns the recorder.
func rawDo(handler http.Handler, method, path string, headers map[string]string, body []byte) *httptest.ResponseRecorder {
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, req)
	return w
}

func TestWhatsAppWebhookRoutes(t *testing.T) {
	const verifyToken = "router-verify-token"
	const appSecret = "router-app-secret"

	const fixture = `{"object":"whatsapp_business_account","entry":[{"changes":[{"field":"messages","value":{"metadata":{"phone_number_id":"PN"},"contacts":[{"wa_id":"111","profile":{"name":"Ann"}}],"messages":[{"from":"111","id":"m1","timestamp":"100","type":"text","text":{"body":"hello"}}]}}]}]}`

	t.Run("GET verification bypasses tenant auth and echoes challenge", func(t *testing.T) {
		t.Setenv("WHATSAPP_VERIFY_TOKEN", verifyToken)
		app := newDefaultApp() // newDefaultApp lives in api_test.go

		// No Authorization / X-Tenant-Id headers at all — Meta sends none.
		w := rawDo(app, http.MethodGet,
			"/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token="+verifyToken+"&hub.challenge=CHAL123",
			nil, nil)
		if w.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200 (tenant auth must NOT apply): %s", w.Code, w.Body.String())
		}
		if w.Body.String() != "CHAL123" {
			t.Errorf("body = %q, want CHAL123 echoed", w.Body.String())
		}
	})

	t.Run("GET with wrong token is 403 (not 401 from tenant auth)", func(t *testing.T) {
		t.Setenv("WHATSAPP_VERIFY_TOKEN", verifyToken)
		app := newDefaultApp()
		w := rawDo(app, http.MethodGet,
			"/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=X",
			nil, nil)
		if w.Code != http.StatusForbidden {
			t.Fatalf("status = %d, want 403", w.Code)
		}
	})

	t.Run("POST with valid signature bypasses tenant auth and accepts", func(t *testing.T) {
		t.Setenv("WHATSAPP_APP_SECRET", appSecret)
		app := newDefaultApp()
		body := []byte(fixture)
		w := rawDo(app, http.MethodPost, "/webhooks/whatsapp",
			map[string]string{"X-Hub-Signature-256": sign(appSecret, body)}, body)
		if w.Code != http.StatusOK {
			t.Fatalf("status = %d, want 200 (tenant auth must NOT apply): %s", w.Code, w.Body.String())
		}
	})

	t.Run("POST without signature is 401 from the receiver, not tenant auth", func(t *testing.T) {
		t.Setenv("WHATSAPP_APP_SECRET", appSecret)
		app := newDefaultApp()
		w := rawDo(app, http.MethodPost, "/webhooks/whatsapp", nil, []byte(fixture))
		if w.Code != http.StatusUnauthorized {
			t.Fatalf("status = %d, want 401", w.Code)
		}
		b := jsonBody(t, w) // jsonBody lives in api_test.go
		if b["error"] != "invalid_signature" {
			t.Errorf("error = %v, want invalid_signature (proves the receiver ran, not tenant auth)", b["error"])
		}
	})

	t.Run("unsupported method on webhook path is 405", func(t *testing.T) {
		app := newDefaultApp()
		w := rawDo(app, http.MethodDelete, "/webhooks/whatsapp", nil, nil)
		if w.Code != http.StatusMethodNotAllowed {
			t.Fatalf("status = %d, want 405", w.Code)
		}
	})

	// Sanity: a normal tenant route still requires auth (we didn't open a hole).
	t.Run("non-webhook route still enforces tenant auth", func(t *testing.T) {
		app := newDefaultApp()
		w := rawDo(app, http.MethodGet, "/v1/tenants/t1/schedules", nil, nil)
		if w.Code != http.StatusUnauthorized {
			t.Fatalf("status = %d, want 401 (tenant auth must still apply to normal routes)", w.Code)
		}
	})
}
